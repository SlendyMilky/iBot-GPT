import nextcord
from nextcord.ext import commands
from nextcord import Interaction, ChannelType, Embed
import os
from openai import OpenAI
import datetime
import logging
import asyncio

# Configuration du logger
logger = logging.getLogger('bot.auto_reply_module')

# Initialiser le client OpenAI
client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))

# Variables d'environnement pour la configuration
auto_reply_forum_ids_str = os.getenv('AUTO_REPLY_FORUM_IDS', '')
enable_detailed_logs = os.getenv('ENABLE_DETAILED_LOGS', 'true').lower() == 'true'

# Liste des forums autorisés via les ID de salon spécifiés dans une variable d'environnement
if auto_reply_forum_ids_str:
    try:
        auto_reply_forum_ids = list(map(int, auto_reply_forum_ids_str.split(',')))
    except ValueError:
        logger.error("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' contient des valeurs invalides.")
        auto_reply_forum_ids = []
else:
    auto_reply_forum_ids = []
    logger.warning("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' est vide ou non définie.")

# Formats d'image supportés
SUPPORTED_IMAGE_FORMATS = ["png", "jpeg", "jpg", "gif", "webp"]

class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: nextcord.Thread):
        if thread.parent_id not in auto_reply_forum_ids:
            return

        # Récupération du premier message du thread
        messages = await thread.history(limit=1).flatten()
        if not messages:
            logger.warning(f"Aucun message trouvé dans le thread: {thread.name} (ID: {thread.id})")
            return

        base_message = messages[0]
        base_content = f"Titre: {thread.name}\nContenu du thread: {base_message.content}"
        logger.info(f"Thread créé par {base_message.author.name} (ID: {base_message.author.id}) dans le forum (ID: {thread.parent_id})")

        image_urls = [attachment.url for attachment in base_message.attachments if any(attachment.url.endswith(ext) for ext in SUPPORTED_IMAGE_FORMATS)]

        # Analyse des images et ajout du contexte au message
        descriptions = {}
        image_cost = 0

        for attachment in base_message.attachments:
            file_extension = attachment.filename.split('.')[-1].lower()
            if file_extension in SUPPORTED_IMAGE_FORMATS:
                try:
                    # Estimation de la taille et du coût des images
                    image_size = attachment.size
                    if image_size > 512 * 512:
                        image_cost += 0.002125  # Coût pour images plus grandes que 512x512
                    else:
                        image_cost += 0.001275  # Coût pour images jusqu'à 512x512

                    response = client.chat.completions.create(
                        model="gpt-4o",
                        messages=[
                            {
                                "role": "user",
                                "content": [
                                    {"type": "text", "text": "Décris cette image du point de vue d'une aide informatique."},
                                    {"type": "image_url", "image_url": {"url": attachment.url}},
                                ],
                            }
                        ],
                        max_tokens=500,
                    )
                    description = response.choices[0].message.content
                    descriptions[attachment.url] = description
                except Exception as e:
                    logger.error(f"Erreur lors de l'appel à l'API d'OpenAI pour la description de l'image: {e}", exc_info=True)
                    descriptions[attachment.url] = "Description non disponible."
            else:
                descriptions[attachment.url] = f"[Fichier non supporté: {attachment.filename}]"

            await asyncio.sleep(1)  # Petite pause pour éviter les rate limits

        base_content = " ".join([base_content] + [descriptions[url] for url in image_urls])

        messages = [
            {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
            {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
            {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown pour mettre le texte en forme (gras, italique, souligné), en mettant en gras les parties importantes. À la fin de ta réponse, n'oublie pas de rappeler qu'il s'agit d'un Discord communautaire."},
            {"role": "user", "content": base_content},
        ]

        if enable_detailed_logs:
            logger.info("Messages envoyés à ChatGPT :")
            for message in messages:
                logger.info(message)

        async with thread.typing():
            response = client.chat.completions.create(
                model="gpt-4o",
                messages=messages
            )

            embed_content = response.choices[0].message.content.strip()
            total_input_tokens = response.usage.total_tokens
            
            # Correction du calcul des coûts
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            input_cost = prompt_tokens * 0.000005 # coût simulant des tokens de prompt de GPT-4o
            output_cost = completion_tokens * 0.000015 # coût simulant des tokens de completion de GPT-4o
            total_cost = input_cost + output_cost + image_cost

            # Fonction pour découper un texte en morceaux de taille maximale tout en conservant les mots entiers
            def split_text(text, max_length=4096):
                words = text.split()
                parts = []
                current_part = words[0]

                for word in words[1:]:
                    if len(current_part) + len(word) + 1 <= max_length:
                        current_part += " " + word
                    else:
                        parts.append(current_part)
                        current_part = word

                parts.append(current_part)
                return parts

            parts = split_text(embed_content, 4000)

            for i, part in enumerate(parts):
                title = f"{'Réponse à la question' if i == 0 else f'Partie : {i+1}'}"
                embed = Embed(title=title, description=part, color=0x454FBF)
                embed.set_footer(text=f"Réponse générée par GPT-4 le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\nTotal Tokens: {response.usage.total_tokens} | Coût: {total_cost:.6f} USD")
                await thread.send(embed=embed)

            logger.info(f"Réponse envoyée dans le thread: {thread.name} (ID: {thread.id})")

def setup(bot):
    bot.add_cog(AutoReply(bot))
