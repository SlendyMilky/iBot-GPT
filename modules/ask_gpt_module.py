import nextcord
from nextcord.ext import commands
from nextcord import Interaction, Embed
import os
from openai import OpenAI
import logging

# Configuration du logger
# logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('bot.ask_gpt_module')

# Initialiser le client OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Liste des rôles non autorisés pour la commande ask-gpt
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

class AskGpt(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="ask-gpt", description="Pose une question à GPT-4o et reçois une réponse")
    async def ask_gpt(self, interaction: Interaction, question: str):
        # Vérification des rôles de l'utilisateur
        if any(role.id in ask_gpt_unauthorized_role_ids for role in interaction.user.roles):
            await interaction.response.send_message("Vous n'avez pas la permission d'utiliser cette commande.", ephemeral=True)
            return

        user = interaction.user
        channel = interaction.channel

        # Log qui a utilisé la commande et dans quel salon
        logger.info(f"Commande /ask-gpt utilisée par {user} dans le salon {channel.name}")

        # Début du traitement en différé
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
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=[system_message, user_message],
                max_tokens=1500
            )

            answer = response.choices[0].message.content
            total_tokens = response.usage.total_tokens
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens

            # Calcul du coût
            input_cost = prompt_tokens * 5 / 1_000_000  # coût des tokens d'entrée
            output_cost = completion_tokens * 15 / 1_000_000  # coût des tokens de sortie
            total_cost = input_cost + output_cost

            embed = Embed(title="Réponse de iBot-GPT", description=answer, color=0x454FBF)
            embed.set_footer(text=f"Total Tokens: {total_tokens} | Coût Total: {total_cost:.6f} USD")

            await interaction.followup.send(embed=embed)
        except Exception as e:
            logger.error(f"Erreur lors de l'appel à l'API d'OpenAI: {e}", exc_info=True)
            await interaction.followup.send(
                content="Une erreur s'est produite lors de l'appel à l'API d'OpenAI.",
            )

def setup(bot):
    bot.add_cog(AskGpt(bot))

# Enregistrer la commande comme dans ping
def initialize_bot(bot):
    setup(bot)
    logger.info("Le module ask-gpt a été initialisé.")
