import nextcord
from nextcord.ext import commands
from nextcord import Interaction, ChannelType, Embed
import os
from openai import AsyncOpenAI
import logging
import asyncio

logger = logging.getLogger('bot.resume_module')

openai_api_key = os.getenv('OPENAI_API_KEY')
if not openai_api_key:
    raise ValueError("La variable d'environnement 'OPENAI_API_KEY' n'est pas définie.")

client = AsyncOpenAI(api_key=openai_api_key)

resume_authorized_role_ids_str = os.getenv('RESUME_AUTHORIZED_ROLE_IDS', '')
if resume_authorized_role_ids_str:
    try:
        resume_authorized_role_ids = list(map(int, resume_authorized_role_ids_str.split(',')))
    except ValueError:
        logger.error("La variable d'environnement 'RESUME_AUTHORIZED_ROLE_IDS' contient des valeurs invalides.")
        resume_authorized_role_ids = []
else:
    resume_authorized_role_ids = []
    logger.warning("La variable d'environnement 'RESUME_AUTHORIZED_ROLE_IDS' est vide ou non définie.")

resume_log_channel_id_str = os.getenv('RESUME_LOG_CHANNEL_ID', '')
resume_log_channel_id = int(resume_log_channel_id_str) if resume_log_channel_id_str.isdigit() else None

SUPPORTED_IMAGE_FORMATS = ["png", "jpeg", "jpg", "gif", "webp"]

DEFAULT_MODEL = "gpt-4o-mini"
MODEL_COST_INPUT = 0.00000015   # $0.15 per 1M
MODEL_COST_OUTPUT = 0.0000006   # $0.60 per 1M


class Resume(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="resume", description="Fait un résumé des messages précédents")
    async def resume(self, interaction: Interaction, num_messages: int = 1, public: bool = False):
        if not any(role.id in resume_authorized_role_ids for role in interaction.user.roles):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        if num_messages > 100:
            await interaction.response.send_message("Le maximum de messages à résumer est de 100.", ephemeral=True)
            return

        if num_messages < 1:
            await interaction.response.send_message("Vous devez demander au moins un message.", ephemeral=True)
            return

        if interaction.channel.type != ChannelType.text:
            await interaction.response.send_message("Cette commande ne peut être utilisée que dans un canal textuel.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=not public)
        progress_message = await interaction.followup.send("En train de générer un résumé... (0%)", ephemeral=not public)

        messages = []
        async for message in interaction.channel.history(limit=num_messages):
            if message.author.bot:
                continue
            messages.append(message)

        if not messages:
            await progress_message.edit(content="Aucun message trouvé.")
            return

        first_message = messages[-1]
        last_message = messages[0]

        descriptions = {}
        image_cost = 0

        messages_with_images = [
            (idx, msg) for idx, msg in enumerate(messages)
            if any(
                attachment.filename.split('.')[-1].lower() in SUPPORTED_IMAGE_FORMATS
                for attachment in msg.attachments
            )
        ]

        for idx, msg in enumerate(messages):
            if msg.attachments:
                for attachment in msg.attachments:
                    file_extension = attachment.filename.split('.')[-1].lower()
                    if file_extension in SUPPORTED_IMAGE_FORMATS:
                        try:
                            img_response = await client.chat.completions.create(
                                model=DEFAULT_MODEL,
                                messages=[
                                    {
                                        "role": "user",
                                        "content": [
                                            {"type": "text", "text": "Décris l'image."},
                                            {"type": "image_url", "image_url": {"url": attachment.url}},
                                        ],
                                    }
                                ],
                                max_completion_tokens=500,
                            )
                            descriptions[attachment.url] = img_response.choices[0].message.content
                            image_cost += (
                                img_response.usage.prompt_tokens * MODEL_COST_INPUT
                                + img_response.usage.completion_tokens * MODEL_COST_OUTPUT
                            )
                            await asyncio.sleep(1)
                        except Exception as e:
                            logger.error(f"Erreur lors de la description de l'image: {e}", exc_info=True)
                            descriptions[attachment.url] = "Description non disponible."
                    else:
                        descriptions[attachment.url] = f"[Fichier non supporté: {attachment.filename}]"

            progress_percent = int((idx + 1) / len(messages) * 100)
            await progress_message.edit(content=f"En train de générer un résumé... ({progress_percent}%)")

        openai_messages = [
            {"role": "system", "content": "Faites un résumé de la conversation."}
        ]

        for msg in reversed(messages):
            formatted_message = (
                f"Pseudo: {msg.author.name}\n"
                f"Heure du message: {msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Message: {msg.content}"
            )
            if msg.attachments:
                for attachment in msg.attachments:
                    if attachment.url in descriptions:
                        formatted_message += f"\n{descriptions[attachment.url]}"
                    else:
                        formatted_message += f"\n[Fichier: {attachment.filename}]"
            openai_messages.append({"role": "user", "content": formatted_message})

        logger.info(f"Commande resume effectuée par: {interaction.user.name}, Nombre de messages: {num_messages}, Public: {public}")

        try:
            response = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=openai_messages,
                max_completion_tokens=500,
            )

            summary = response.choices[0].message.content
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            total_tokens = response.usage.total_tokens
            total_cost = prompt_tokens * MODEL_COST_INPUT + completion_tokens * MODEL_COST_OUTPUT + image_cost

            embed = Embed(title=f"Résumé des messages ({num_messages} messages)", description=summary, color=0x454FBF)
            embed.set_footer(text=f"Total Tokens: {total_tokens} | Total Cost: {total_cost:.6f} USD")
            embed.add_field(name="Premier message", value=f"[Lien]({first_message.jump_url})", inline=True)
            embed.add_field(name="Dernier message", value=f"[Lien]({last_message.jump_url})", inline=True)

            await progress_message.edit(embed=embed, content=None)

            if resume_log_channel_id:
                log_channel = self.bot.get_channel(resume_log_channel_id)
                if log_channel:
                    log_embed = Embed(title=f"Résumé des messages ({num_messages} messages)", description=summary, color=0x454FBF)
                    log_embed.set_footer(text=f"Total Tokens: {total_tokens} | Total Cost: {total_cost:.6f} USD")
                    log_embed.add_field(name="Premier message", value=f"[Lien]({first_message.jump_url})", inline=True)
                    log_embed.add_field(name="Dernier message", value=f"[Lien]({last_message.jump_url})", inline=True)
                    log_embed.add_field(name="Commande par", value=interaction.user.name, inline=False)
                    await log_channel.send(embed=log_embed)

        except Exception as e:
            logger.error(f"Erreur lors de l'appel à l'API d'OpenAI: {e}", exc_info=True)
            await progress_message.edit(content="Une erreur s'est produite lors de l'appel à l'API d'OpenAI.")


def setup(bot):
    bot.add_cog(Resume(bot))
