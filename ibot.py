import openai
import nextcord
import logging
import datetime
import os
import re
from nextcord.ext import commands

Discord_Forum_Name = os.environ['Discord_Forum_Name']
Bot_Token = os.environ['Discord_Bot_Token']

# Set up logging to console and file
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler("thread_log.txt")])

# Configure OpenAI API
openai.api_key = os.environ['GPT_KEY']
openai.model = os.environ['GPT_MODEL']

# Create a new bot
bot = commands.Bot(command_prefix="§")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name="t'aider dans %s" % Discord_Forum_Name))

@bot.event
async def on_thread_create(thread):
    if thread.parent.name == os.environ['Discord_Forum_Name']:

        # Fetch the base message in the thread
        base_message = await thread.fetch_message(thread.id)

        # Log user who created the thread
        logging.info(f"Thread created by user {base_message.author.id}")

        # Get the content of the base message
        base_content = base_message.content

        async with thread.typing():
            # Send the base content to GPT-3.5 Turbo and generate the response
            response = openai.ChatCompletion.create(
                model=openai.model,
                messages=[
                    {
                        "role": "system",
                        "content": f"Date du jour : {datetime.datetime.now()}"
                    },
                    {
                        "role": "system",
                        "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."
                    },
                    {
                        "role": "system",
                        "content": "Tu es un expert en informatique. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique, et non sur le sujet évoqué. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un discord communautaire."
                    },
                    {
                        "role": "user",
                        "content": base_content
                    }
                ]
            )

            # Log that response is generated
            logging.info(f"Response generated at {datetime.datetime.now()}")

            # Get the generated response from GPT-3.5 Turbo
            generated_response = response['choices'][0]['message']['content'].strip()

            # Replace double line breaks with a single line break
            generated_response = generated_response.replace('\n\n', '\n')

            # Split the output into less than 2000 characters chunks preserving line breaks
            split_response = re.findall('.{1,2000}(?:\n|$)', generated_response, re.DOTALL)

            for message_part in split_response:
                # Send each chunk as a message to the thread
                await thread.send(message_part)

# Run the bot
bot.run(Bot_Token)
