import nextcord
from nextcord.ext import commands
import os
import glob
import logging

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')

intents = nextcord.Intents.default()
intents.message_content = True  # Activer les intents de contenu de message

bot = commands.Bot(command_prefix="§", intents=intents)

# Configuration du logger
logger = logging.getLogger('bot')
logger.setLevel(logging.INFO)

formatter = logging.Formatter('%(asctime)s [%(name)s] %(message)s', datefmt='%d/%m/%Y %H:%M:%S')

stream_handler = logging.StreamHandler()
stream_handler.setFormatter(formatter)

file_handler = logging.FileHandler("bot_log.txt")
file_handler.setFormatter(formatter)

logger.addHandler(stream_handler)
logger.addHandler(file_handler)

def load_modules():
    for filename in glob.glob("./modules/*.py"):
        if filename.endswith(".py"):
            module_name = os.path.basename(filename)[:-3]
            bot.load_extension(f"modules.{module_name}")

@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user.name} - {bot.user.id}")
    await bot.sync_application_commands()

if __name__ == "__main__":
    load_modules()
    bot.run(BOT_TOKEN)
