import os
import re
import logging
import datetime
import openai
import nextcord
from nextcord.ext import commands

Discord_Forum_Name = os.getenv('Discord_Forum_Name')
Bot_Token = os.getenv('Discord_Bot_Token')

openai.api_key = os.getenv('GPT_KEY')
openai.model = os.getenv('GPT_MODEL')

logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("thread_log.txt")])

bot = commands.Bot(command_prefix="§")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name=f"t'aider dans {Discord_Forum_Name}"))

@bot.event
async def on_thread_create(thread):
    if thread.parent.name == os.getenv('Discord_Forum_Name'):
        base_message = await thread.fetch_message(thread.id)
        base_content = f"Titre: {thread.name}\nContenue du thread: {base_message.content}"
        logging.info(f"Thread created by user {base_message.author.id}")

        async with thread.typing():
            response = openai.ChatCompletion.create(
                model=openai.model,
                messages=[
                    {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                    {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
                    {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."},
                    {"role": "user", "content": base_content}
                ]
            )

            logging.info(f"Response generated at {datetime.datetime.now()}")
            generated_response = response['choices'][0]['message']['content'].strip()
            generated_response = re.sub('\n\n', '\n', generated_response)
            split_response = re.findall('.{1,2000}(?:\n|$)', generated_response, re.DOTALL)

            for message_part in split_response:
                await thread.send(message_part)

bot.run(Bot_Token)
