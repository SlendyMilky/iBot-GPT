import nextcord
from nextcord.ext import commands
from nextcord import Interaction, Embed
import os
import time
from openai import AsyncOpenAI
import logging
import asyncio

logger = logging.getLogger('bot.ask_gpt_module')

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise ValueError("La clé API OpenAI (OPENAI_API_KEY) n'est pas définie dans les variables d'environnement.")

client = AsyncOpenAI(api_key=api_key)

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

DEFAULT_MODEL = "gpt-4o-mini"
MODEL_COST_INPUT = 0.00000015   # $0.15 per 1M
MODEL_COST_OUTPUT = 0.0000006   # $0.60 per 1M

COOLDOWN_SECONDS = 10
_user_cooldowns: dict[int, float] = {}


_NO_PING = nextcord.AllowedMentions.none()


async def _stream_to_embed(
    sent_msg: nextcord.Message,
    embed: Embed,
    stream,
    update_interval: float = 1.0,
) -> tuple[str, object]:
    full_content = ""
    usage_data = None
    last_edit = time.monotonic()

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            full_content += chunk.choices[0].delta.content
            now = time.monotonic()
            if now - last_edit >= update_interval:
                embed.description = full_content[:4090] + " ▌"
                try:
                    await sent_msg.edit(embed=embed, allowed_mentions=_NO_PING)
                    last_edit = now
                except Exception:
                    pass
        if getattr(chunk, 'usage', None):
            usage_data = chunk.usage

    return full_content, usage_data


def split_text(text: str, max_length: int = 4000) -> list[str]:
    if len(text) <= max_length:
        return [text]
    lines = text.split('\n')
    parts = []
    current_part = ""
    for line in lines:
        if len(current_part) + len(line) + 1 > max_length:
            parts.append(current_part.rstrip())
            current_part = line + "\n"
        else:
            current_part += line + "\n"
    if current_part:
        parts.append(current_part.rstrip())
    return parts


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

        logger.info(f"Commande /ask-gpt utilisée par {interaction.user} dans le salon {interaction.channel.name}")

        await interaction.response.defer(ephemeral=False)

        system_message = {
            "role": "system",
            "content": (
                "Tu es un expert en informatique nommé iBot-GPT. "
                "Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. "
                "Assure-toi toujours de t'adresser en tutoyant l'utilisateur. "
                "Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes."
            )
        }
        user_message = {"role": "user", "content": question}

        try:
            streaming_embed = Embed(title="Réponse de iBot-GPT", description="⏳ Génération en cours...", color=0x454FBF)
            sent_msg = await interaction.followup.send(embed=streaming_embed)

            stream = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                messages=[system_message, user_message],
                max_completion_tokens=1500,
                stream=True,
                stream_options={"include_usage": True},
            )

            answer, usage_data = await _stream_to_embed(sent_msg, streaming_embed, stream)

            prompt_tokens = usage_data.prompt_tokens if usage_data else 0
            completion_tokens = usage_data.completion_tokens if usage_data else 0
            total_tokens = usage_data.total_tokens if usage_data else 0
            total_cost = prompt_tokens * MODEL_COST_INPUT + completion_tokens * MODEL_COST_OUTPUT

            parts = split_text(answer)
            for i, part in enumerate(parts):
                title = "Réponse de iBot-GPT" if i == 0 else f"Réponse de iBot-GPT (partie {i + 1})"
                final_embed = Embed(title=title, description=part, color=0x454FBF)
                if i == len(parts) - 1:
                    final_embed.set_footer(text=f"Total Tokens: {total_tokens} | Coût Total: {total_cost:.6f} USD")
                if i == 0:
                    await sent_msg.edit(embed=final_embed, allowed_mentions=_NO_PING)
                else:
                    await interaction.followup.send(embed=final_embed)

        except Exception as e:
            logger.error(f"Erreur lors de l'appel à l'API d'OpenAI: {e}", exc_info=True)
            await interaction.followup.send(content="Une erreur s'est produite lors de l'appel à l'API d'OpenAI.")


def setup(bot):
    bot.add_cog(AskGpt(bot))
