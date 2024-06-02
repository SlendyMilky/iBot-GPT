import nextcord
from nextcord.ext import commands
from nextcord import Interaction, ChannelType, Embed
import os
from openai import OpenAI
import logging

# Configuration du logger
logger = logging.getLogger('bot.resume_module')

# Initialiser le client OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Liste des rôles autorisés pour la commande resume
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

class Resume(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @nextcord.slash_command(name="resume", description="Fait un résumé des messages précédents")
    async def resume(self, interaction: Interaction, num_messages: int = 1, public: bool = False):
        # Vérification des rôles de l'utilisateur
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

        messages = []
        async for message in interaction.channel.history(limit=num_messages):
            if message.author.bot:
                continue
            messages.append(message)

        descriptions = {}
        total_input_tokens = 0
        image_cost = 0

        for msg in messages:
            if msg.attachments:
                for attachment in msg.attachments:
                    try:
                        # Estimation de la taille et du coût des images
                        image_size = attachment.size
                        if image_size > 512 * 512:
                            image_cost += 0.002125  # Coût pour images plus grandes que 512*512
                        else:
                            image_cost += 0.001275  # Coût pour images jusqu'à 512*512

                        response = client.chat.completions.create(
                            model="gpt-4o",
                            messages=[
                                {
                                    "role": "user",
                                    "content": [
                                        {"type": "text", "text": "Décris l'image."},
                                        {"type": "image_url", "image_url": {"url": attachment.url}},
                                    ],
                                }
                            ],
                            max_tokens=500,
                        )
                        description = response.choices[0].message.content
                        descriptions[attachment.url] = description
                    except Exception as e:
                        logger.error(f"Erreur lors de l'appel à l'API d'OpenAI pour la description de l'image: {e}")
                        descriptions[attachment.url] = "Description non disponible."

        openai_messages = [
            {"role": "system", "content": "Faites un résumé de la conversation."}
        ]

        for msg in reversed(messages):
            formatted_message = f"Pseudo: {msg.author.name}\nHeure du message: {msg.created_at.strftime('%Y-%m-%d %H:%M:%S')}\nMessage: {msg.content}"
            token_estimate = len(formatted_message.split())
            total_input_tokens += token_estimate

            if msg.attachments:
                for attachment in msg.attachments:
                    if attachment.url in descriptions:
                        formatted_message += f"\nDescription de l'image envoyée : {descriptions[attachment.url]}"
                    else:
                        formatted_message += f"\n[Lien de l'image: {attachment.url}]"

            openai_messages.append({"role": "user", "content": formatted_message})

        logger.info(f"Commande resume effectuée par: {interaction.user.name}, Nombre de messages: {num_messages}, Public: {public}")

        try:
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=openai_messages,
                max_tokens=500
            )

            summary = response.choices[0].message.content
            total_output_tokens = response.usage['total_tokens']

            # Calcul des coûts
            input_cost = total_input_tokens * 5 / 1_000_000
            output_cost = total_output_tokens * 15 / 1_000_000
            total_cost = input_cost + output_cost + image_cost

            embed = Embed(title="Résumé des messages", description=summary, color=0x00ff00)
            embed.set_footer(text=f"Total Tokens: {total_input_tokens + total_output_tokens} | Total Cost: {total_cost:.6f} USD")

            await interaction.followup.send(embed=embed, ephemeral=not public)
        except Exception as e:
            logger.error(f"Erreur lors de l'appel à l'API d'OpenAI: {e}")
            await interaction.followup.send(
                "Une erreur s'est produite lors de l'appel à l'API d'OpenAI.",
                ephemeral=True
            )

def setup(bot):
    bot.add_cog(Resume(bot))
