# modules/events.py
import nextcord
import logging
from nextcord.ext import commands
from .config import FORUM_CHANNEL_IDS, GPT_CHANNEL_ID, openai_client, async_openai_client
from .utils import split_text, generate_response

bot = commands.Bot(command_prefix="§")
bot.message_context = {}

@bot.event
async def on_ready():
    print(f"We have logged in as {bot.user}")
    await bot.change_presence(activity=nextcord.Game(name="t'aider dans les forums"))

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
        await generate_response(message, bot.message_context, async_openai_client)
    else:
        await bot.process_commands(message)

@bot.event
async def on_thread_create(thread):
    if str(thread.parent.id) in FORUM_CHANNEL_IDS:
        base_message = await thread.fetch_message(thread.id)
        base_content = f"Titre: {thread.name}\nContenu du thread: {base_message.content}"
        logging.info(f"Thread created by user {base_message.author.name} {base_message.author.id}")

        from .gpt import handle_thread  # Import here to avoid circular import
        await handle_thread(thread, base_message, base_content, openai_client)

async def setup(bot):
    await bot.add_cog(Events(bot))
