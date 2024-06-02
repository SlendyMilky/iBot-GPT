# modules/config.py
import os
from openai import OpenAI, AsyncOpenAI

# Initialisation des variables d'environnement
FORUM_CHANNEL_IDS = os.getenv('FORUM_CHANNEL_IDS', '').split(',')
BOT_TOKEN = os.getenv('BOT_TOKEN')
GPT_CHANNEL_ID = os.getenv('GPT_CHANNEL_ID')

# Initialisation de l'API OpenAI
openai_client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
async_openai_client = AsyncOpenAI(api_key=os.getenv('OPENAI_API_KEY'))
