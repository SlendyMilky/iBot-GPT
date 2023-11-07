import os
import re
import logging
import datetime
import openai
import nextcord
from nextcord.ext import commands

FORUM_CHANNEL_NAME = os.getenv('FORUM_CHANNEL_NAME')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ASK_GPT_ROLES_ALLOWED = os.getenv('ASK_GPT_ROLES_ALLOWED')
ASK_GPT4_ROLES_ALLOWED = os.getenv('ASK_GPT4_ROLES_ALLOWED')

openai.api_key = os.getenv('OPENAI_API_KEY')

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("thread_log.txt")])

bot = commands.Bot(command_prefix="§")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name=f"t'aider dans {FORUM_CHANNEL_NAME}"))

# Auto respons to forum channel ======================================================================
@bot.event
async def on_thread_create(thread):
    if thread.parent.name == os.getenv('FORUM_CHANNEL_NAME'):
        base_message = await thread.fetch_message(thread.id)
        base_content = f"Titre: {thread.name}\nContenue du thread: {base_message.content}"
        logging.info(f"Thread created by user {base_message.author.name} {base_message.author.id}")

        async with thread.typing():
            response = openai.ChatCompletion.create(
                model="gpt-4-1106-preview",
                messages=[
                    {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                    {"role": "system", "content": "Fait un titre court de la question"},
                    {"role": "user", "content": base_content}
                ]
            )

            logging.info(f"Title generated at {datetime.datetime.now()}")
            embed_title = response['choices'][0]['message']['content'].strip()
            embed_title = re.sub('\n\n', '\n', embed_title)
            
            response_text = openai.ChatCompletion.create(
                model="gpt-4-1106-preview",
                messages=[
                    {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                    {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
                    {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."},
                    {"role": "user", "content": base_content}
                ]
            )
            
            logging.info(f"Response content generated for forum at {datetime.datetime.now()}")
            embed_content = response_text['choices'][0]['message']['content'].strip()
            embed_content = re.sub('\n\n', '\n', embed_content)
            
            if len(embed_content) <= 4096:
                embed = nextcord.Embed(title=embed_title, description=embed_content, color=0x265d94)
                embed.set_footer(text=f"Réponse générée par gpt-4-turbo le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                await thread.send(embed=embed)
            else:
                part_num = thread.parent.threads.index(thread) + 1
                part_title = f"Partie {part_num}"
                part_embed = nextcord.Embed(title=part_title, description=embed_content, color=0x265d94)
                part_embed.set_footer(text=f"Réponse générée par gpt-4-turbo le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
                await thread.send(embed=part_embed)
# Auto respons to forum channel ======================================================================





# Slash command ask-gpt ======================================================================
@bot.slash_command(name="ask-gpt", description="Demander une réponse de chatgpt")
async def ask_gpt(ctx, message: str):
    member = None
    if ctx.guild is not None:
        member = await ctx.guild.fetch_member(ctx.user.id)
    user_roles_ids = [str(role.id) for role in member.roles]
    allowed_roles = ASK_GPT_ROLES_ALLOWED.split(', ')
    if not any(role_id in user_roles_ids for role_id in allowed_roles):
        await ctx.response.send_message("Tu n'es pas autorisé a faire cette commande.", ephemeral=True)
        logging.info(f"Received slash command from unauthorized user : {ctx.user.name} {ctx.user.id}")
        return

    logging.info(f"Received ask-gpt command from {ctx.user.name} {ctx.user.id}")
    await ctx.response.defer()
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
            {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
            {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."},
            {"role": "user", "content": message.replace('\n\n', '\n')}
        ]
    )
    logging.info(f"Response content of ask-gpt generated at {datetime.datetime.now()}")

    response_message = response['choices'][0]['message']['content']
    message_chunks = [response_message[i:i + 2000] for i in range(0, len(response_message), 2000)]

    for message_chunk in message_chunks:
        await ctx.followup.send(message_chunk)
# Slash command ask-gpt ======================================================================




# Slash command ask-gpt-4 ======================================================================
@bot.slash_command(name="ask-gpt-4", description="Demander une réponse de chatgpt-4")
async def ask_gpt_4(ctx, message: str):
    member = None
    if ctx.guild is not None:
        member = await ctx.guild.fetch_member(ctx.user.id)
    user_roles_ids = [str(role.id) for role in member.roles]
    allowed_roles = ASK_GPT4_ROLES_ALLOWED.split(', ')
    if not any(role_id in user_roles_ids for role_id in allowed_roles):
        await ctx.response.send_message("Tu n'es pas autorisé a faire cette commande.", ephemeral=True)
        logging.info(f"Received slash command from unauthorized user : {ctx.user.name} {ctx.user.id}")
        return

    logging.info(f"Received ask-gpt-4 command from {ctx.user.name} {ctx.user.id}")
    await ctx.response.defer()
    response = openai.ChatCompletion.create(
        model="gpt-4-1106-preview",
        messages=[
            {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
            {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
            {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."},
            {"role": "user", "content": message.replace('\n\n', '\n')}
        ]
    )
    logging.info(f"Response content of ask-gpt-4 generated at {datetime.datetime.now()}")
    
    response_message = response['choices'][0]['message']['content']
    message_chunks = [response_message[i:i + 2000] for i in range(0, len(response_message), 2000)]
   
    for message_chunk in message_chunks:
        await ctx.followup.send(message_chunk)
# Slash command ask-gpt-4 ======================================================================

bot.run(BOT_TOKEN)
