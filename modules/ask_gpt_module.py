import nextcord
from nextcord.ext import commands
from nextcord import Interaction, Embed
import os
import time
import logging

from ._claude import (
    BASE_PERSONA, NO_PING, blocked_message, finalize, friendly_error, route, split_text, stream_reply,
)

logger = logging.getLogger('bot.ask_gpt_module')

ask_gpt_unauthorized_role_ids_str = os.getenv('ASK_GPT_UNAUTHORIZED_ROLE_IDS', '')
if ask_gpt_unauthorized_role_ids_str:
    try:
        ask_gpt_unauthorized_role_ids = list(map(int, ask_gpt_unauthorized_role_ids_str.split(',')))
    except ValueError:
        logger.error("La variable d'environnement 'ASK_GPT_UNAUTHORIZED_ROLE_IDS' contient des valeurs invalides.")
        ask_gpt_unauthorized_role_ids = []
else:
    ask_gpt_unauthorized_role_ids = []
    logger.warning("La variable d'environnement 'ASK_GPT_UNAUTHORIZED_ROLE_IDS' est vide ou non définie.")

COOLDOWN_SECONDS = 10
_user_cooldowns: dict[int, float] = {}


class AskGpt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="ask-gpt", description="Pose une question à iBot-GPT et reçois une réponse")
    async def ask_gpt(self, interaction: Interaction, question: str):
        if any(role.id in ask_gpt_unauthorized_role_ids for role in interaction.user.roles):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        user_id = interaction.user.id
        now = time.monotonic()
        last_used = _user_cooldowns.get(user_id, 0)
        remaining = COOLDOWN_SECONDS - (now - last_used)
        if remaining > 0:
            await interaction.response.send_message(
                f"Merci de patienter encore **{remaining:.1f}s** avant de réutiliser cette commande.",
                ephemeral=True,
            )
            return
        _user_cooldowns[user_id] = now

        choice = await route(self.bot, interaction.guild, interaction.user, 'ask')
        if choice is None:
            await interaction.response.send_message(blocked_message(), ephemeral=True)
            return

        logger.info(f"Commande /ask-gpt utilisée par {interaction.user} dans le salon {interaction.channel.name}")

        await interaction.response.defer(ephemeral=False)

        sent_msg = None
        try:
            streaming_embed = Embed(title="Réponse de iBot-GPT", description="⏳ Génération en cours...", color=0x454FBF)
            sent_msg = await interaction.followup.send(embed=streaming_embed)

            async def show_partial(text: str):
                streaming_embed.description = text[:4090] + " ▌"
                await sent_msg.edit(embed=streaming_embed, allowed_mentions=NO_PING)

            reply = await stream_reply(
                choice, BASE_PERSONA, [{"role": "user", "content": question}], max_tokens=4096,
                user_id=user_id, feature='ask', on_text=show_partial,
            )

            answer, _ = finalize(reply)
            footer = f"{choice.model} | Total Tokens: {reply.input_tokens + reply.output_tokens} | Coût: {reply.cost:.6f} USD"
            if choice.note:
                footer = f"{choice.note}\n{footer}"

            parts = split_text(answer)
            for i, part in enumerate(parts):
                title = "Réponse de iBot-GPT" if i == 0 else f"Réponse de iBot-GPT (partie {i + 1})"
                final_embed = Embed(title=title, description=part, color=0x454FBF)
                if i == len(parts) - 1:
                    final_embed.set_footer(text=footer)
                if i == 0:
                    await sent_msg.edit(embed=final_embed, allowed_mentions=NO_PING)
                else:
                    await interaction.followup.send(embed=final_embed)

        except Exception as e:
            message = friendly_error(e)
            if sent_msg:
                await sent_msg.edit(content=message, embed=None)
            else:
                await interaction.followup.send(content=message)


def setup(bot):
    bot.add_cog(AskGpt(bot))
