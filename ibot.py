import os
import re
import logging
import datetime
import openai
import nextcord
from nextcord.ext import commands

# Initialization de variables environnement
FORUM_CHANNEL_NAME = os.getenv('FORUM_CHANNEL_NAME')
BOT_TOKEN = os.getenv('BOT_TOKEN')
ASK_GPT_ROLES_ALLOWED = set(os.getenv('ASK_GPT_ROLES_ALLOWED', '').split(','))
ASK_GPT4_ROLES_ALLOWED = set(os.getenv('ASK_GPT4_ROLES_ALLOWED', '').split(','))
GPT_CHANNEL_ID = int(os.getenv('GPT_CHANNEL_ID', 0))

openai.api_key = os.getenv('OPENAI_API_KEY')

# Configuration du logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p')

# Définition du bot Nextcord
bot = commands.Bot(command_prefix="§")

def setup_logging():
    logger = logging.getLogger()
    handler_stream = logging.StreamHandler()
    handler_file = logging.FileHandler("thread_log.txt")
    logger.addHandler(handler_stream)
    logger.addHandler(handler_file)

setup_logging()

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name=f"aider dans {FORUM_CHANNEL_NAME}"))

# General function to get openai chat response
async def get_openai_response(model, messages):
    return openai.ChatCompletion.create(model=model, messages=messages)

@bot.event
async def on_thread_create(thread):
    if thread.parent.name == FORUM_CHANNEL_NAME:
        base_message = await thread.fetch_message(thread.id)
        base_content = f"Titre: {thread.name}\nContenu du thread: {base_message.content}"
        logging.info(f"Thread created by {base_message.author.name} {base_message.author.id}")

        async with thread.typing():
            embed_title, embed_content = await generate_forum_response(base_content)

            embed = nextcord.Embed(title=embed_title, description=embed_content[:4096], color=0x265d94)
            embed.set_footer(text=f"Réponse générée le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
            await thread.send(embed=embed)


async def generate_forum_response(base_content):
    title_response = await get_openai_response("gpt-4-0125-preview", generate_system_messages("Fait un titre court de la question") + [{"role": "user", "content": base_content}])
    content_response = await get_openai_response("gpt-4-0125-preview", generate_system_messages() + [{"role": "user", "content": base_content}])

    embed_title = title_response['choices'][0]['message']['content'].strip()
    embed_content = content_response['choices'][0]['message']['content'].strip()

    embed_title = re.sub('\n\n', '\n', embed_title)
    embed_content = re.sub('\n\n', '\n', embed_content)

    return embed_title, embed_content

def generate_system_messages(custom_message=None):
    base_messages = [
        {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
        {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
        {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."}
    ]
    if custom_message:
        base_messages.append({"role": "system", "content": custom_message})
    return base_messages

@bot.event
async def on_message(message):
    if message.author.bot or message.channel.id != GPT_CHANNEL_ID:
        return

    await process_gpt_channel_message(message)

@bot.slash_command(name="ask-gpt", description="Demander une réponse de chatgpt")
async def ask_gpt_slash_command(ctx, message: str):
    await process_slash_command(ctx, message, "gpt-3.5-turbo", ASK_GPT_ROLES_ALLOWED)

@bot.slash_command(name="ask-gpt-4", description="Demander une réponse de chatgpt-4")
async def ask_gpt_4_slash_command(ctx, message: str):
    await process_slash_command(ctx, message, "gpt-4-1106-preview", ASK_GPT4_ROLES_ALLOWED)

async def process_gpt_channel_message(message):
    async with message.channel.typing():
        response_msg = await get_openai_response("gpt-4-1106-preview", generate_system_messages())
        await message.channel.send(response_msg['choices'][0]['message']['content'], reference=message)

async def process_slash_command(ctx, message, model, allowed_roles):
    if not set(str(role.id) for role in getattr(ctx.user, 'roles', [])) & allowed_roles:
        await ctx.response.send_message("Tu n'es pas autorisé à faire cette commande.", ephemeral=True)
        return

    response = await get_openai_response(model, generate_system_messages() + [{"role": "user", "content": message}])
    await ctx.response.send_message(response['choices'][0]['message']['content'])

bot.run(BOT_TOKEN)
