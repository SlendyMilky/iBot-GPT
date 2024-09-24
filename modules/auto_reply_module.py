import nextcord
from nextcord.ext import commands
from nextcord import Embed
import os
from openai import OpenAI
import datetime
import logging
import asyncio
import redis
import json  # Ajoutez cette importation en haut du fichier

# Configuration du logger
logger = logging.getLogger('bot.auto_reply_module')
# logging.basicConfig(level=logging.DEBUG)

# Assurez-vous que la clé API est définie
api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    logger.error("La clé API 'OPENAI_API_KEY' n'est pas définie dans les variables d'environnement.")
    raise EnvironmentError("La clé API 'OPENAI_API_KEY' doit être définie.")

# Initialiser le client OpenAI
try:
    client = OpenAI(api_key=api_key)
except Exception as e:
    logger.error(f"Erreur lors de l'initialisation du client OpenAI: {e}")
    raise

# Configuration de Redis
redis_host = os.getenv('REDIS_HOST')
redis_port = os.getenv('REDIS_PORT', 6379)  # Port par défaut de Redis
redis_client = redis.Redis(host=redis_host, port=redis_port)

# Variables d'environnement pour la configuration
auto_reply_forum_ids_str = os.getenv('AUTO_REPLY_FORUM_IDS', '')
enable_detailed_logs = os.getenv('ENABLE_DETAILED_LOGS', 'false').lower() == 'true'

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
        # Vérification des tags du thread en utilisant 'applied_tags'
        tags = [tag.name for tag in thread.applied_tags]
        if "No GPT" in tags:
            logger.info(f"Tag 'No GPT' détecté dans le thread: {thread.name} (ID: {thread.id}). Aucune action n'est effectuée.")
            return  # Arrêt de la fonction si le tag "No GPT" est présent

        # Vérifier si le tag 'GPT-Helper' est présent
        if "GPT-Helper" in tags:
            # Ajout du contexte système pour GPT-Helper
            system_message = {
                "role": "system",
                "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown compatible embed discord."
            }
            # Ajouter ce message dans Redis au début de la conversation du thread
            redis_client.lpush(f"thread:{thread.id}", json.dumps(system_message))
            # Continuer avec les autres actions spécifiques pour 'GPT-Helper'
            pass
        else:
            # Actions par défaut si 'GPT-Helper' n'est pas présent
            # Sélection du modèle basé sur les tags
            model = "gpt-4o"  # Modèle par défaut
            model_cost_input = 0.000005  # Coût par token d'entrée pour gpt-4o
            model_cost_output = 0.000015  # Coût par token de sortie pour gpt-4o
            if "gpt-3.5" in tags:
                model = "gpt-3.5-turbo"  # Modèle moins cher si le tag est présent
                model_cost_input = 0.000003  # Coût par token d'entrée pour gpt-3.5-turbo
                model_cost_output = 0.000006  # Coût par token de sortie pour gpt-3.5-turbo
            elif "gpt-4-turbo" in tags:
                model = "gpt-4-turbo"
                model_cost_input = 0.00001  # Coût par token d'entrée pour gpt-4-turbo
                model_cost_output = 0.00003  # Coût par token de sortie pour gpt-4-turbo

            if thread.parent_id not in auto_reply_forum_ids:
                return
            
            await asyncio.sleep(2)  # Ajouter un délai de 2 secondes pour s'assurer que le message initial est disponible

            # Récupération du premier message du thread
            messages = await thread.history(limit=1).flatten()
            if not messages:
                logger.warning(f"Aucun message trouvé dans le thread: {thread.name} (ID: {thread.id})")
                return

            base_message = messages[0]
            user_name = base_message.author.name
            base_content = f"Pseudo: {user_name}\nTitre: {thread.name}\nContenu du thread: {base_message.content}"
            logger.info(f"Thread créé par {user_name} (ID: {base_message.author.id}) dans le forum (ID: {thread.parent_id})")

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

            # Ajout des descriptions des images au contenu de base
            if descriptions:
                image_descriptions = "\n".join([f"URL: {url}\nDescription: {desc}" for url, desc in descriptions.items()])
                base_content += f"\nDescriptions des images:\n{image_descriptions}"

            messages = [
                {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
                {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown compatible embed discord."},
                {"role": "user", "content": base_content},
            ]

            if enable_detailed_logs:
                logger.debug("Messages envoyés à ChatGPT :")
                for message in messages:
                    logger.debug(message)

            async with thread.typing():
                response = client.chat.completions.create(
                    model=model,  # Utilisation du modèle sélectionné
                    messages=messages
                )

                embed_content = response.choices[0].message.content.strip()
                total_input_tokens = response.usage.total_tokens
                
                # Correction du calcul des coûts
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                input_cost = prompt_tokens * model_cost_input  # coût simulant des tokens de prompt
                output_cost = completion_tokens * model_cost_output  # coût simulant des tokens de completion
                total_cost = input_cost + output_cost + image_cost

                # Fonction pour découper un texte en morceaux de taille maximale tout en conservant les mots entiers
                def split_text(text, max_length=4096):
                    lines = text.split('\n')
                    parts = []
                    current_part = ""

                    for line in lines:
                        if len(current_part) + len(line) + 1 <= max_length:
                            current_part += line + "\n"
                        else:
                            parts.append(current_part)
                            current_part = line + "\n"

                    parts.append(current_part)
                    return parts

                parts = split_text(embed_content, 4000)

                for i, part in enumerate(parts):
                    title = f"{'Réponse à la question' if i == 0 else f'Partie : {i+1}'}"
                    embed = Embed(title=title, description=part, color=0x454FBF)
                    embed.set_footer(text=f"Réponse générée par {model} le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\nTotal Tokens: {response.usage.total_tokens} | Coût: {total_cost:.6f} USD")
                    await thread.send(embed=embed)

                logger.info(f"Réponse envoyée dans le thread: {thread.name} (ID: {thread.id})")

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return  # Ignorer les messages du bot lui-même

        thread = message.channel
        if isinstance(thread, nextcord.Thread) and thread.parent_id in auto_reply_forum_ids:
            tags = [tag.name for tag in thread.applied_tags]
            if "GPT-Helper" in tags:
                # Récupérer la conversation depuis Redis
                conversation = redis_client.lrange(f"thread:{thread.id}", 0, -1)
                conversation = [json.loads(msg.decode('utf-8')) for msg in conversation]
                new_message = {
                    "role": "user",
                    "content": message.content
                }
                conversation.append(new_message)

                # Limiter la conversation aux N derniers messages ou tokens
                conversation = limit_conversation(conversation, max_tokens=4096)

                # Formatage des messages pour l'API d'OpenAI
                formatted_messages = []
                for msg in conversation:
                    formatted_message = {"role": msg["role"], "content": msg["content"]}
                    formatted_messages.append(formatted_message)

                # Appel à OpenAI pour obtenir une réponse
                response = client.chat.completions.create(
                    model="gpt-4o",
                    messages=formatted_messages,
                    max_tokens=4096
                )

                # Envoyer la réponse du modèle
                bot_response = response.choices[0].message.content
                await send_large_message(message, bot_response)  # Utilisation de la nouvelle fonction pour gérer les grands messages

                # Ajouter la réponse du bot à la conversation avec le rôle 'assistant'
                bot_message = {
                    "role": "assistant",
                    "content": bot_response
                }
                conversation.append(bot_message)

                # Sérialiser et mettre à jour la conversation dans Redis
                redis_client.rpush(f"thread:{thread.id}", json.dumps(new_message))
                redis_client.rpush(f"thread:{thread.id}", json.dumps(bot_message))

    @commands.command()
    async def index_thread(self, ctx, thread_id: int):
        thread = await self.bot.fetch_channel(thread_id)
        messages = await thread.history(limit=None).flatten()
        total = len(messages)
        count = 0

        temp_message = await ctx.send("Indexation en cours... 0%")
        for message in messages:
            # Indexer chaque message dans Redis
            redis_client.rpush(f"thread:{thread_id}", json.dumps({"role": "user", "content": message.content}))
            count += 1
            if count % 10 == 0:
                percentage = (count / total) * 100
                await temp_message.edit(content=f"Indexation en cours... {percentage:.1f}%")

        await temp_message.edit(content="Indexation terminée.")

async def send_large_message(message, content, max_length=2000):
    if len(content) <= max_length:
        await message.reply(content, mention_author=False)
    else:
        lines = content.split('\n')
        current_part = ""
        for line in lines:
            if len(current_part) + len(line) + 1 > max_length:
                await message.reply(current_part, mention_author=False)
                current_part = line + "\n"
            else:
                current_part += line + "\n"
        if current_part:
            await message.reply(current_part, mention_author=False)

def limit_conversation(conversation, max_tokens=4096):
    total_tokens = 0
    limited_conversation = []
    for msg in reversed(conversation):
        msg_tokens = len(msg["content"].split())  # Estimation simple du nombre de tokens
        if total_tokens + msg_tokens > max_tokens:
            break
        limited_conversation.append(msg)
        total_tokens += msg_tokens
    return list(reversed(limited_conversation))

def setup(bot):
    bot.add_cog(AutoReply(bot))