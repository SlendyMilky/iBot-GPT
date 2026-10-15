import nextcord
from nextcord.ext import commands
from nextcord import Interaction, Embed
import logging

from . import _usage
from ._claude import HARD_USD, SOFT_USD, is_admin

logger = logging.getLogger('bot.usage_module')


class Usage(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="usage", description="Consommation IA du mois : la tienne, ou celle d'un membre (admins)")
    async def usage(
        self,
        interaction: Interaction,
        membre: nextcord.Member = nextcord.SlashOption(description="Membre à consulter (admins uniquement)", required=False),
    ):
        target = membre or interaction.user
        if target.id != interaction.user.id and not await is_admin(self.bot, interaction.user):
            await interaction.response.send_message("Seuls les administrateurs peuvent consulter l'usage d'un autre membre.", ephemeral=True)
            return

        month = _usage.month_key()
        rows = _usage.month_breakdown(target.id, month)
        total_cost = sum(r[4] for r in rows)

        if await self.bot.is_owner(target):
            budget = "illimité (créateur du bot)"
        elif total_cost >= HARD_USD:
            budget = f"**épuisé** ({total_cost:.2f} / {HARD_USD:g} $)"
        elif total_cost >= SOFT_USD:
            budget = f"mode économique Haiku ({total_cost:.2f} / {HARD_USD:g} $)"
        else:
            budget = f"{total_cost:.2f} / {SOFT_USD:g} $ avant le mode économique"

        embed = Embed(title=f"Usage de {target.display_name} — {month}", color=0x454FBF)
        embed.add_field(name="Coût", value=f"{total_cost:.4f} USD", inline=True)
        embed.add_field(name="Requêtes", value=str(sum(r[1] for r in rows)), inline=True)
        embed.add_field(name="Budget", value=budget, inline=False)
        embed.add_field(
            name="Tokens",
            value=f"{sum(r[2] for r in rows):,} en entrée / {sum(r[3] for r in rows):,} en sortie".replace(",", " "),
            inline=False,
        )
        if rows:
            embed.add_field(
                name="Par modèle",
                value="\n".join(f"`{m}` · {n} req · {i:,} / {o:,} tokens · {c:.4f} $".replace(",", " ") for m, n, i, o, c in rows),
                inline=False,
            )
        await interaction.response.send_message(embed=embed, ephemeral=True)


def setup(bot):
    bot.add_cog(Usage(bot))
