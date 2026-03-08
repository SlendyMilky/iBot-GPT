import nextcord
from nextcord.ext import commands
from nextcord import Embed
import os
import time
from openai import AsyncOpenAI
import datetime
import logging
import asyncio
import json

logger = logging.getLogger('bot.auto_reply_module')

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    logger.error("La clé API 'OPENAI_API_KEY' n'est pas définie dans les variables d'environnement.")
    raise EnvironmentError("La clé API 'OPENAI_API_KEY' doit être définie.")

client = AsyncOpenAI(api_key=api_key)

REDIS_ENABLED = os.getenv('REDIS_ENABLED', 'true').lower() == 'true'

if REDIS_ENABLED:
    import redis.asyncio as aioredis
    _redis_client = aioredis.Redis(
        host=os.getenv('REDIS_HOST', 'localhost'),
        port=int(os.getenv('REDIS_PORT', 6379)),
    )
    logger.info("Stockage Redis activé.")
else:
    _redis_client = None
    logger.warning("Redis désactivé (REDIS_ENABLED=false). Le mode GPT-Helper utilisera un stockage en mémoire (non persistant).")

# In-memory fallback store when Redis is disabled: key -> list of JSON strings
_memory_store: dict[str, list[str]] = {}


async def storage_rpush(key: str, value: str) -> None:
    if _redis_client:
        await _redis_client.rpush(key, value)
    else:
        _memory_store.setdefault(key, []).append(value)


async def storage_lrange(key: str, start: int, end: int) -> list[bytes]:
    if _redis_client:
        return await _redis_client.lrange(key, start, end)
    items = _memory_store.get(key, [])
    if end == -1:
        end = len(items)
    return [item.encode('utf-8') for item in items[start:end + 1 if end != len(items) else end]]


async def storage_delete(key: str) -> None:
    if _redis_client:
        await _redis_client.delete(key)
    else:
        _memory_store.pop(key, None)


async def storage_expire(key: str, ttl: int) -> None:
    if _redis_client:
        await _redis_client.expire(key, ttl)

auto_reply_forum_ids_str = os.getenv('AUTO_REPLY_FORUM_IDS', '')
enable_detailed_logs = os.getenv('ENABLE_DETAILED_LOGS', 'false').lower() == 'true'

if auto_reply_forum_ids_str:
    try:
        auto_reply_forum_ids = list(map(int, auto_reply_forum_ids_str.split(',')))
    except ValueError:
        logger.error("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' contient des valeurs invalides.")
        auto_reply_forum_ids = []
else:
    auto_reply_forum_ids = []
    logger.warning("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' est vide ou non définie.")

SUPPORTED_IMAGE_FORMATS = ["png", "jpeg", "jpg", "gif", "webp"]

# Model configuration: model name -> (cost_per_input_token, cost_per_output_token)
MODEL_CONFIG = {
    "gpt-4o-mini":  (0.00000015, 0.0000006),   # $0.15 / $0.60 per 1M
    "gpt-4.1-mini": (0.0000004,  0.0000016),    # $0.40 / $1.60 per 1M
    "gpt-5":        (0.00000125, 0.00001),       # $1.25 / $10.00 per 1M
    "gpt-4o":       (0.0000025,  0.00001),       # $2.50 / $10.00 per 1M
}

TAG_TO_MODEL = {
    "gpt-4.1-mini": "gpt-4.1-mini",
    "gpt-5":        "gpt-5",
    "gpt-4o":       "gpt-4o",
}

DEFAULT_MODEL = "gpt-4o-mini"
REDIS_TTL = 30 * 24 * 3600  # 30 jours


def select_model(tags: list[str]) -> str:
    for tag, model in TAG_TO_MODEL.items():
        if tag in tags:
            return model
    return DEFAULT_MODEL


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


_NO_PING = nextcord.AllowedMentions.none()


async def _stream_to_embed(
    sent_msg: nextcord.Message,
    embed: Embed,
    stream,
    update_interval: float = 1.0,
) -> tuple[str, object]:
    """Stream API chunks into a Discord embed, editing it at most once per second."""
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


async def _stream_to_plain(
    sent_msg: nextcord.Message,
    stream,
    update_interval: float = 1.0,
) -> tuple[str, object]:
    """Stream API chunks into a plain Discord message, editing it at most once per second."""
    full_content = ""
    usage_data = None
    last_edit = time.monotonic()

    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            full_content += chunk.choices[0].delta.content
            now = time.monotonic()
            if now - last_edit >= update_interval:
                display = full_content[:1990] + " ▌"
                try:
                    await sent_msg.edit(content=display, allowed_mentions=_NO_PING)
                    last_edit = now
                except Exception:
                    pass
        if getattr(chunk, 'usage', None):
            usage_data = chunk.usage

    return full_content, usage_data


def limit_conversation(conversation: list[dict], max_tokens: int = 4096) -> list[dict]:
    system_messages = [msg for msg in conversation if msg["role"] == "system"]
    non_system = [msg for msg in conversation if msg["role"] != "system"]

    # Rough token estimate: words * 1.3
    system_tokens = sum(len(msg["content"].split()) * 1.3 for msg in system_messages)
    total_tokens = system_tokens
    limited = []

    for msg in reversed(non_system):
        msg_tokens = len(msg["content"].split()) * 1.3
        if total_tokens + msg_tokens > max_tokens:
            break
        limited.append(msg)
        total_tokens += msg_tokens

    return system_messages + list(reversed(limited))


class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: nextcord.Thread):
        tags = [tag.name for tag in thread.applied_tags]

        if "No GPT" in tags:
            logger.info(f"Tag 'No GPT' détecté dans le thread: {thread.name} (ID: {thread.id}). Aucune action n'est effectuée.")
            return

        if "GPT-Helper" not in tags:
            if thread.parent_id not in auto_reply_forum_ids:
                return

            model = select_model(tags)
            cost_input, cost_output = MODEL_CONFIG[model]

            await asyncio.sleep(2)

            messages = [m async for m in thread.history(limit=1, oldest_first=True)]
            if not messages:
                logger.warning(f"Aucun message trouvé dans le thread: {thread.name} (ID: {thread.id})")
                return

            base_message = messages[0]
            user_name = base_message.author.name
            base_content = f"Titre du thread: {thread.name}\n{user_name}: {base_message.content}"
            logger.info(f"Thread créé par {user_name} (ID: {base_message.author.id}) dans le forum (ID: {thread.parent_id})")

            descriptions = {}
            image_cost = 0

            try:
                # Analyse des images avec indicateur de saisie
                if base_message.attachments:
                    async with thread.typing():
                        for attachment in base_message.attachments:
                            file_extension = attachment.filename.split('.')[-1].lower()
                            if file_extension in SUPPORTED_IMAGE_FORMATS:
                                try:
                                    img_response = await client.chat.completions.create(
                                        model="gpt-4o-mini",
                                        messages=[
                                            {
                                                "role": "user",
                                                "content": [
                                                    {"type": "text", "text": "Décris cette image du point de vue d'une aide informatique."},
                                                    {"type": "image_url", "image_url": {"url": attachment.url}},
                                                ],
                                            }
                                        ],
                                        max_completion_tokens=500,
                                    )
                                    descriptions[attachment.url] = img_response.choices[0].message.content
                                    image_cost += (
                                        img_response.usage.prompt_tokens * 0.00000015
                                        + img_response.usage.completion_tokens * 0.0000006
                                    )
                                except Exception as e:
                                    logger.error(f"Erreur lors de la description de l'image: {e}", exc_info=True)
                                    descriptions[attachment.url] = "Description non disponible."
                            else:
                                descriptions[attachment.url] = f"[Fichier non supporté: {attachment.filename}]"
                            await asyncio.sleep(1)

                if descriptions:
                    image_descriptions = "\n".join(
                        [f"URL: {url}\nDescription: {desc}" for url, desc in descriptions.items()]
                    )
                    base_content += f"\nDescriptions des images:\n{image_descriptions}"

                openai_messages = [
                    {"role": "system", "content": f"Date du jour : {datetime.datetime.now()}"},
                    {"role": "system", "content": "Si la question posée te semble incorrecte ou manque de détails, n'hésite pas à demander à l'utilisateur des informations supplémentaires. Étant donné que tu as uniquement accès à son message initial, avoir le maximum d'informations sera utile pour fournir une aide optimale."},
                    {"role": "system", "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown compatible embed discord."},
                    {"role": "user", "content": base_content},
                ]

                if enable_detailed_logs:
                    logger.debug("Messages envoyés à l'API :")
                    for msg in openai_messages:
                        logger.debug(msg)

                # Envoi de l'embed initial pour le streaming
                streaming_embed = Embed(title="Réponse à la question", description="⏳ Génération en cours...", color=0x454FBF)
                sent_msg = await thread.send(embed=streaming_embed)

                stream = await client.chat.completions.create(
                    model=model,
                    messages=openai_messages,
                    stream=True,
                    stream_options={"include_usage": True},
                )

                full_content, usage_data = await _stream_to_embed(sent_msg, streaming_embed, stream)
                full_content = full_content.strip()

                total_tokens = usage_data.total_tokens if usage_data else 0
                prompt_tokens = usage_data.prompt_tokens if usage_data else 0
                completion_tokens = usage_data.completion_tokens if usage_data else 0
                total_cost = prompt_tokens * cost_input + completion_tokens * cost_output + image_cost

                # Mise à jour finale avec le contenu complet et le footer
                parts = split_text(full_content)
                for i, part in enumerate(parts):
                    title = "Réponse à la question" if i == 0 else f"Partie : {i + 1}"
                    final_embed = Embed(title=title, description=part, color=0x454FBF)
                    final_embed.set_footer(
                        text=f"Réponse générée par {model} le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                             f"Total Tokens: {total_tokens} | Coût: {total_cost:.6f} USD"
                    )
                    if i == 0:
                        await sent_msg.edit(embed=final_embed, allowed_mentions=_NO_PING)
                    else:
                        await thread.send(embed=final_embed)

                logger.info(f"Réponse envoyée dans le thread: {thread.name} (ID: {thread.id})")

            except Exception as e:
                logger.error(f"Erreur lors du traitement du thread {thread.id}: {e}", exc_info=True)
                error_embed = Embed(
                    title="Erreur",
                    description="Une erreur s'est produite lors de la génération de la réponse. Merci de réessayer ou de contacter un administrateur.",
                    color=0xFF0000,
                )
                await thread.send(embed=error_embed)

        else:
            system_message = {
                "role": "system",
                "content": "Tu es un expert en informatique nommé iBot-GPT. Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur que ce serveur est axé sur l'informatique. Assure-toi toujours de t'adresser en tutoyant l'utilisateur. Pour améliorer la lisibilité, utilise le markdown compatible embed discord."
            }
            key = f"thread:{thread.id}"
            await storage_rpush(key, json.dumps(system_message))
            await storage_expire(key, REDIS_TTL)

    @commands.Cog.listener()
    async def on_message(self, message: nextcord.Message):
        if message.author == self.bot.user:
            return

        thread = message.channel
        if not (isinstance(thread, nextcord.Thread) and thread.parent_id in auto_reply_forum_ids):
            return

        tags = [tag.name for tag in thread.applied_tags]
        if "GPT-Helper" not in tags:
            return

        key = f"thread:{thread.id}"
        raw_conversation = await storage_lrange(key, 0, -1)
        conversation = [json.loads(msg.decode('utf-8')) for msg in raw_conversation]

        new_message = {
            "role": "user",
            "content": f"{message.author.name}: {message.content}"
        }
        conversation.append(new_message)
        conversation = limit_conversation(conversation, max_tokens=4096)

        if message.reference and message.reference.message_id:
            referenced_message = await message.channel.fetch_message(message.reference.message_id)
            if referenced_message.author != self.bot.user:
                await storage_rpush(key, json.dumps(new_message))
                await storage_expire(key, REDIS_TTL)
                return
        elif message.author.id != thread.owner_id:
            await storage_rpush(key, json.dumps(new_message))
            await storage_expire(key, REDIS_TTL)
            return

        model = select_model(tags)

        formatted_messages = [{"role": msg["role"], "content": msg["content"]} for msg in conversation]

        try:
            no_ping = nextcord.AllowedMentions.none()
            sent_msg = await message.reply("⏳ Génération en cours...", mention_author=False, allowed_mentions=no_ping)

            stream = await client.chat.completions.create(
                model=model,
                messages=formatted_messages,
                max_completion_tokens=4096,
                stream=True,
                stream_options={"include_usage": True},
            )

            bot_response, _ = await _stream_to_plain(sent_msg, stream)

            # Mise à jour finale et découpage si nécessaire
            parts = split_text(bot_response, 2000)
            await sent_msg.edit(content=parts[0], allowed_mentions=_NO_PING)
            for part in parts[1:]:
                await message.reply(part, mention_author=False, allowed_mentions=no_ping)

        except Exception as e:
            logger.error(f"Erreur API lors du traitement du message dans {thread.id}: {e}", exc_info=True)
            await message.reply("Une erreur s'est produite lors de la génération de la réponse.", mention_author=False, allowed_mentions=nextcord.AllowedMentions.none())
            return

        bot_message = {"role": "assistant", "content": bot_response}

        await storage_rpush(key, json.dumps(new_message))
        await storage_rpush(key, json.dumps(bot_message))
        await storage_expire(key, REDIS_TTL)

    @nextcord.slash_command(name="unindex", description="Supprime l'indexation du thread actuel dans Redis.")
    async def unindex_thread(self, interaction: nextcord.Interaction):
        thread = interaction.channel
        if not isinstance(thread, nextcord.Thread) or thread.parent_id not in auto_reply_forum_ids:
            await interaction.response.send_message("Cette commande ne peut être utilisée que dans un thread autorisé.", ephemeral=True)
            return

        await storage_delete(f"thread:{thread.id}")
        await interaction.response.send_message("Indexation supprimée avec succès.", ephemeral=True)

    @nextcord.slash_command(name="debug_redis", description="Affiche le contenu brut des messages indexés dans Redis pour ce thread.")
    async def debug_redis(self, interaction: nextcord.Interaction, count: int = 10):
        thread = interaction.channel
        if not isinstance(thread, nextcord.Thread) or thread.parent_id not in auto_reply_forum_ids:
            await interaction.response.send_message("Cette commande ne peut être utilisée que dans un thread autorisé.", ephemeral=True)
            return

        messages = await storage_lrange(f"thread:{thread.id}", 0, count - 1)
        messages = [msg.decode('utf-8') for msg in messages]

        response_content = "\n".join(messages) if messages else "Aucun message indexé trouvé."
        await interaction.response.send_message(f"Contenu brut des messages indexés :\n{response_content}", ephemeral=True)


async def send_large_message(message: nextcord.Message, content: str, max_length: int = 2000):
    no_ping = nextcord.AllowedMentions.none()
    parts = split_text(content, max_length)
    for part in parts:
        await message.reply(part, mention_author=False, allowed_mentions=no_ping)


def setup(bot):
    bot.add_cog(AutoReply(bot))
