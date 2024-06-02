import nextcord
from nextcord.ext import commands
from nextcord import Interaction
import logging

# Configuration du logger
logger = logging.getLogger('bot.ping_module')

class Ping(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="ping", description="Vérifie si le bot fonctionne et montre des informations utiles")
    async def ping(self, interaction: Interaction):
        latency = round(self.bot.latency * 1000)  # Latence en millisecondes
        await interaction.response.send_message(
            f"Le bot fonctionne !\nLatence du bot: {latency}ms",
            ephemeral=True  # Visible uniquement par celui qui a lancé la commande
        )
        logger.info(f"Commande /ping exécutée par {interaction.user} avec une latence de {latency}ms")

def setup(bot):
    bot.add_cog(Ping(bot))