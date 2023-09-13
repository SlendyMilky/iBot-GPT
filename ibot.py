import openai
import nextcord
import textwrap
import logging
import datetime
import os
from nextcord.ext import commands

Discord_Forum_Name = os.environ["Discord_Forum_Name"]
Bot_Token = os.environ["Discord_Bot_Token"]

# Set up logging to console and file
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s %(message)s',
                    datefmt='%m/%d/%Y %I:%M:%S %p',
                    handlers=[logging.StreamHandler(),
                              logging.FileHandler()"thread_log.txt")])

# Configure OpenAI API
openai.api_key = os.environ["GPT_KEY"]

# Create a new bot
bot = commands.Bot(command_prefix="!")

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name="t'aider dans" % Discord_Forum_Name))

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
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": "Tu es un expert de l'informatique. Toutes questions ne concernant pas l'informatique dit simplement que ce serveur est basé sur l'informatique et non le domaine évoqué. Utilise toujours le tutoiement pour t'adresser à l'utilisateur. Utilise le markdown pour rendre le texte plus facilement lisible (gras, italique, sous ligné) met en gras les parties importantes. A la fin de ta réponse rappel qu'il s'agit d'un discord communautaire et non un centre professionnel d'aide."
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

        # Split the output into less than 2000 characters chunks
        split_response = textwrap.wrap(generated_response, 2000)

        for message_part in split_response:
            # Send each chunk as a message to the thread
            await thread.send(message_part)

# Run the bot
if Bot_Token is None:
    print("Bot_Token is not set properly.")
else:
    bot.run(Bot_Token)
