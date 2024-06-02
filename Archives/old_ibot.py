import os
import re
import logging
import datetime
from openai import OpenAI, AsyncOpenAI
import nextcord
from nextcord.ext import commands

# Initialisation des variables d'environnement
FORUM_CHANNEL_IDS = os.getenv('FORUM_CHANNEL_IDS', '').split(',')
BOT_TOKEN = os.getenv('BOT_TOKEN')
GPT_CHANNEL_ID = os.getenv('GPT_CHANNEL_ID')

# Initialisation de l'API OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
async_openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("thread_log.txt")])

bot = commands.Bot(command_prefix="§")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name="t'aider dans les forums"))
    bot.message_context = {}

# Fonction pour découper un texte en morceaux de taille maximale tout en conservant les mots entiers
def split_text(text, max_length=4096):
    words = text.split()
    parts = []
    current_part = words[0]

    for word in words[1:]:
        if len(current_part) + len(word) + 1 <= max_length:
            current_part += " " + word
        else:
            parts.append(current_part)
            current_part = word

    parts.append(current_part)
    return parts

@bot.event
async def on_thread_create(thread):
    if str(thread.parent.id) in FORUM_CHANNEL_IDS:
        base_message = await thread.fetch_message(thread.id)
        base_content = f"Titre: {thread.name}\nContenu du thread: {base_message.content}"
        logging.info(f"Thread created by user {base_message.author.name} {base_message.author.id}")
        
        image_urls = [attachment.url for attachment in base_message.attachments if attachment.url.endswith(('.jpg', '.jpeg', '.png', '.gif'))]

        async with thread.typing():
            messages = [
                {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                {"role": "system", "content": "Faites un titre court de la question"},
                {"role": "user", "content": base_content}
            ]
            
            if image_urls:
                for image_url in image_urls:
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": base_content},
                            {"type": "image_url", "image_url": image_url}
                        ]
                    })
                    base_content = ""  # Après avoir ajouté l'image, sinon il serait envoyé encore et encore comme 'user'
            else:
                messages.append({"role": "user", "content": base_content})

            response = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages
            )

            logging.info(f"Title generated at {datetime.datetime.now()}")
            embed_title = response.choices[0].message.content.strip()
            embed_title = re.sub('\n\n', '\n', embed_title)

            messages = [
                {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
                {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un Discord communautaire."},
            ]

            if image_urls:
                for image_url in image_urls:
                    messages.append({
                        "role": "user",
                        "content": [
                            {"type": "text", "text": base_content},
                            {"type": "image_url", "image_url": image_url}
                        ]
                    })
            else:
                messages.append({"role": "user", "content": base_content})

            response_text = openai_client.chat.completions.create(
                model="gpt-4o",
                messages=messages
            )
            
            logging.info(f"Response content generated for forum at {datetime.datetime.now()}")
            embed_content = response_text.choices[0].message.content.strip()
            parts = split_text(embed_content, 4000)
            
            for i, part in enumerate(parts):
                title = embed_title if i == 0 else f"Partie : {i+1}"
                embed = nextcord.Embed(title=title, description=part, color=0x265d94)
                embed.set_footer(text=f"Réponse générée par gpt-4o le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                await thread.send(embed=embed)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    
    try:
        specific_channel_id = int(GPT_CHANNEL_ID)
    except ValueError:
        logging.error(f"GPT_CHANNEL_ID environment variable is not a valid integer: {GPT_CHANNEL_ID}")
        return
    
    if message.channel.id == specific_channel_id:
        if message.reference and isinstance(message.reference.resolved, nextcord.Message):
            referenced_message = message.reference.resolved
            logging.info(f"Message is a reply: {referenced_message.clean_content}")
            role = "assistant" if bot.user.id == referenced_message.author.id else "user"
            formatted_message = {"role": role, "content": referenced_message.clean_content}
            bot.message_context.setdefault(message.channel.id, []).append(formatted_message)
        else:
            bot.message_context[message.channel.id] = []
        
        content = message.clean_content or message.content
        if not content and message.attachments:
            content = "Pièce jointe: " + ", ".join(attachment.url for attachment in message.attachments)

        if not content:
            logging.info(f"User {message.author.name} sent a message without text content.")
            await message.channel.send("Tu n'as envoyé aucun texte. Envoie-moi une question ou un message textuel !", reference=message)
            return

        user_message = {"role": "user", "content": content}
        bot.message_context[message.channel.id].append(user_message)
        logging.info(f"Appended user's message to context for channel {message.channel.id}")
        await generate_response(message)
    else:
        await bot.process_commands(message)

async def generate_response(message):
    context = bot.message_context.get(message.channel.id, [])
    logging.info(f"Generating response with context: {context}")
    if context:
        async with message.channel.typing():
            try:
                response = await async_openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[
                        {"role": "system", "content": f"Date du jour : {datetime.datetime.now()} Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique."},
                    ] + context + [
                        {"role": "user", "content": message.clean_content}
                    ]
                )
                response_content = response.choices[0].message.content.strip()
                parts = split_text(response_content, 4000)

                for i, part in enumerate(parts):
                    title = "Réponse de iBot-GPT" if i == 0 else f"Partie : {i+1}"
                    embed = nextcord.Embed(title=title, description=part, color=0x265d94)
                    embed.set_footer(text=f"Réponse générée par gpt-4o le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                    await message.channel.send(embed=embed)
                logging.info("Bot successfully sent a response in the channel.")
            except Exception as e:
                logging.error(f"Error while generating or sending response: {e}")
    else:
        logging.info("No context available, not sending a response.")

@bot.slash_command(name="ask-gpt", description="Demander une réponse de chatgpt avec un contexte optionnel.")
async def ask_gpt(ctx, message_count: int = 0, message: str = ""):
    if message_count < 0 or message_count > 50:
        await ctx.response.send_message("Le nombre de messages précédents doit être compris entre 0 et 50.", ephemeral=True)
        return

    logging.info(f"Received ask-gpt command from {ctx.user.name} {ctx.user.id}")
    await ctx.response.defer()

    channel = ctx.channel
    previous_messages = []
    
    async for msg in channel.history(limit=message_count):
        if msg.clean_content:
            previous_messages.append({"role": "user" if msg.author == ctx.user else "assistant", "content": msg.clean_content})
        if msg.attachments:
            for attachment in msg.attachments:
                if attachment.url.endswith(('jpg', 'jpeg', 'png', 'gif')):
                    previous_messages.append({"role": "user" if msg.author == ctx.user else "assistant", "content": [{"type": "image_url", "image_url": attachment.url}]})

    previous_messages.reverse()
    messages = [{"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique."}]
    messages.extend(previous_messages)
    messages.append({"role": "user", "content": message})

    response = await async_openai_client.chat.completions.create(
        model="gpt-4o",
        messages=messages
    )

    logging.info(f"Response content of ask-gpt generated at {datetime.datetime.now()}")
    
    response_message = response.choices[0].message.content
    parts = split_text(response_message, 4000)

    for i, part in enumerate(parts):
        title = "Réponse de iBot-GPT" if i == 0 else f"Partie : {i+1}"
        embed = nextcord.Embed(title=title, description=part, color=0x265d94)
        embed.set_footer(text=f"Réponse générée par gpt-4o le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
        await ctx.followup.send(embed=embed)

bot.run(BOT_TOKEN)
