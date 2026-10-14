import nextcord
from nextcord.ext import commands
from nextcord import Interaction, ChannelType, Embed
import os
import logging

from ._claude import MAX_IMAGES, NO_PING, blocked_message, finalize, friendly_error, image_blocks, route, stream_reply

logger = logging.getLogger('bot.resume_module')

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

SYSTEM_PROMPT = (
    "Fais un résumé de la conversation fournie, en français, sous forme de puces concises "
    "(3500 caractères maximum). Si des images sont jointes, tiens-en compte."
)


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

        choice = await route(self.bot, interaction.guild, interaction.user, 'resume')
        if choice is None:
            await interaction.response.send_message(blocked_message(), ephemeral=True)
            return

        await interaction.response.defer(ephemeral=not public)
        progress_message = await interaction.followup.send("En train de générer un résumé...", ephemeral=not public)

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

        # Un seul message user, dans l'ordre chronologique : texte de chaque message suivi de ses images
        # (au plus MAX_IMAGES images au total, en partant des plus récentes).
        images_left = MAX_IMAGES
        content_by_message = {}
        for msg in messages:
            blocks, skipped = await image_blocks(msg.attachments, limit=images_left)
            images_left -= len(blocks)
            text = (
                f"Pseudo: {msg.author.name}\n"
                f"Heure du message: {msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"Message: {msg.content}"
            )
            if skipped:
                text += "\n" + "\n".join(f"[Fichier joint non analysé : {name}]" for name in skipped)
            content_by_message[msg.id] = [{"type": "text", "text": text}, *blocks]

        content = [block for msg in reversed(messages) for block in content_by_message[msg.id]]

        logger.info(f"Commande resume effectuée par: {interaction.user.name}, Nombre de messages: {num_messages}, Public: {public}")

        try:
            reply = await stream_reply(
                choice, SYSTEM_PROMPT, [{"role": "user", "content": content}], max_tokens=2048,
                user_id=interaction.user.id, feature='resume',
            )
            summary, _ = finalize(reply)

            footer = f"{choice.model} | Total Tokens: {reply.input_tokens + reply.output_tokens} | Total Cost: {reply.cost:.6f} USD"
            if choice.note:
                footer = f"{choice.note}\n{footer}"

            embed = Embed(title=f"Résumé des messages ({num_messages} messages)", description=summary[:4096], color=0x454FBF)
            embed.set_footer(text=footer)
            embed.add_field(name="Premier message", value=f"[Lien]({first_message.jump_url})", inline=True)
            embed.add_field(name="Dernier message", value=f"[Lien]({last_message.jump_url})", inline=True)

            await progress_message.edit(embed=embed, content=None)

            if resume_log_channel_id:
                log_channel = self.bot.get_channel(resume_log_channel_id)
                if log_channel:
                    log_embed = Embed(title=f"Résumé des messages ({num_messages} messages)", description=summary[:4096], color=0x454FBF)
                    log_embed.set_footer(text=footer)
                    log_embed.add_field(name="Premier message", value=f"[Lien]({first_message.jump_url})", inline=True)
                    log_embed.add_field(name="Dernier message", value=f"[Lien]({last_message.jump_url})", inline=True)
                    log_embed.add_field(name="Commande par", value=interaction.user.name, inline=False)
                    await log_channel.send(embed=log_embed, allowed_mentions=NO_PING)

        except Exception as e:
            await progress_message.edit(content=friendly_error(e))


def setup(bot):
    bot.add_cog(Resume(bot))
