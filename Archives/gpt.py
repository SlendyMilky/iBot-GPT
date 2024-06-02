# modules/gpt.py
import datetime
import re
import logging
import nextcord
from .utils import split_text

async def handle_thread(thread, base_message, base_content, openai_client):
    image_urls = [attachment.url for attachment in base_message.attachments if attachment.url.endswith(('.jpg', '.jpeg', '.png', '.gif'))]

    async with thread.typing():
        messages = [
            {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
            {"role": "system", "content": "Faites un titre court de la question"},
            {"role": "user", "content": base_content}
        ]
        
        if image_urls:
            for image_url in image_urls:
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": base_content},
                    {"type": "image_url", "image_url": image_url}
                ]})
                base_content = ""

        response = openai_client.chat.completions.create(
            model="gpt-4o",
            messages=messages
        )

        logging.info(f"Title generated at {datetime.datetime.now()}")
        embed_title = response.choices[0].message.content.strip()
        embed_title = re.sub('\n\n', '\n', embed_title)

        messages = [
            {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
            {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires...."},
        ]

        if image_urls:
            for image_url in image_urls:
                messages.append({"role": "user", "content": [
                    {"type": "text", "text": base_content},
                    {"type": "image_url", "image_url": image_url}
                ]})
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

async def generate_response(message, message_context, async_openai_client):
    context = message_context.get(message.channel.id, [])
    logging.info(f"Generating response with context: {context}")
    if context:
        async with message.channel.typing():
            try:
                response = await async_openai_client.chat.completions.create(
                    model="gpt-4o",
                    messages=[{"role": "system", "content": f"Date du jour : {datetime.datetime.now()} Tu es un expert en informatique nommé iBot-GPT...."}] + context + [
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
