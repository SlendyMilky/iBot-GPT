import nextcord
from nextcord.ext import commands
from nextcord import Embed
import os
import datetime
import logging
import asyncio
import json

from ._claude import (
    BASE_PERSONA, NO_PING, blocked_message, finalize, friendly_error, image_blocks, is_admin,
    normalize_history, route, should_notify, split_text, stream_reply,
)

logger = logging.getLogger('bot.auto_reply_module')

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

if auto_reply_forum_ids_str:
    try:
        auto_reply_forum_ids = list(map(int, auto_reply_forum_ids_str.split(',')))
    except ValueError:
        logger.error("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' contient des valeurs invalides.")
        auto_reply_forum_ids = []
else:
    auto_reply_forum_ids = []
    logger.warning("La variable d'environnement 'AUTO_REPLY_FORUM_IDS' est vide ou non définie.")

REDIS_TTL = 30 * 24 * 3600  # 30 jours
HELPER_HISTORY_TOKENS = 16000  # budget d'historique envoyé à chaque tour (estimation)

# Le prompt système n'est plus stocké dans Redis : il est passé à chaque appel.
HELPER_SYSTEM = (
    f"{BASE_PERSONA} Les messages de la conversation sont au format \"pseudo: message\" ; "
    "plusieurs personnes peuvent intervenir."
)


def limit_conversation(conversation: list[dict], max_tokens: int = HELPER_HISTORY_TOKENS) -> list[dict]:
    """Garde les messages les plus récents qui tiennent dans le budget (~3 caractères par token)."""
    kept, total = [], 0.0
    for msg in reversed(conversation):
        total += len(msg["content"]) / 3
        if total > max_tokens:
            break
        kept.append(msg)
    return kept[::-1]


class AutoReply(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: nextcord.Thread):
        tags = [tag.name for tag in thread.applied_tags]

        if "No GPT" in tags:
            logger.info(f"Tag 'No GPT' détecté dans le thread: {thread.name} (ID: {thread.id}). Aucune action n'est effectuée.")
            return

        # GPT-Helper : rien à faire à la création, l'historique se construit message par message.
        if "GPT-Helper" in tags or thread.parent_id not in auto_reply_forum_ids:
            return

        await asyncio.sleep(2)

        messages = [m async for m in thread.history(limit=1, oldest_first=True)]
        if not messages:
            logger.warning(f"Aucun message trouvé dans le thread: {thread.name} (ID: {thread.id})")
            return

        base_message = messages[0]
        author = base_message.author
        logger.info(f"Thread créé par {author.name} (ID: {author.id}) dans le forum (ID: {thread.parent_id})")

        choice = await route(self.bot, thread.guild, author, 'forum', opus="Opus" in tags)
        if choice is None:
            if should_notify(author.id):
                await thread.send(blocked_message(), allowed_mentions=NO_PING)
            return

        sent_msg = None
        try:
            images, skipped = await image_blocks(base_message.attachments)
            base_content = f"Titre du thread: {thread.name}\n{author.name}: {base_message.content}"
            if skipped:
                base_content += "\n" + "\n".join(f"[Fichier joint non analysé : {name}]" for name in skipped)

            system = (
                f"{BASE_PERSONA} Si la question posée te semble incorrecte ou manque de détails, "
                "n'hésite pas à demander à l'utilisateur des informations supplémentaires. "
                "Étant donné que tu as uniquement accès à son message initial, avoir le maximum "
                "d'informations sera utile pour fournir une aide optimale. "
                f"Date du jour : {datetime.date.today():%d/%m/%Y}."
            )
            messages_api = [{"role": "user", "content": [*images, {"type": "text", "text": base_content}]}]

            streaming_embed = Embed(title="Réponse à la question", description="⏳ Génération en cours...", color=0x454FBF)
            sent_msg = await thread.send(embed=streaming_embed)

            async def show_partial(text: str):
                streaming_embed.description = text[:4090] + " ▌"
                await sent_msg.edit(embed=streaming_embed, allowed_mentions=NO_PING)

            reply = await stream_reply(
                choice, system, messages_api, max_tokens=8192,
                user_id=author.id, feature='forum', on_text=show_partial,
            )

            answer, _ = finalize(reply)
            footer = (
                f"Réponse générée par {choice.model} le {datetime.datetime.now().strftime('%d/%m/%Y %H:%M:%S')}\n"
                f"Total Tokens: {reply.input_tokens + reply.output_tokens} | Coût: {reply.cost:.6f} USD"
            )
            if choice.note:
                footer = f"{choice.note}\n{footer}"

            parts = split_text(answer)
            for i, part in enumerate(parts):
                title = "Réponse à la question" if i == 0 else f"Partie : {i + 1}"
                final_embed = Embed(title=title, description=part, color=0x454FBF)
                final_embed.set_footer(text=footer)
                if i == 0:
                    await sent_msg.edit(embed=final_embed, allowed_mentions=NO_PING)
                else:
                    await thread.send(embed=final_embed)

            logger.info(f"Réponse envoyée dans le thread: {thread.name} (ID: {thread.id})")

        except Exception as e:
            logger.error(f"Erreur lors du traitement du thread {thread.id}: {e}")
            error_embed = Embed(title="Erreur", description=friendly_error(e), color=0xFF0000)
            if sent_msg:
                await sent_msg.edit(embed=error_embed)
            else:
                await thread.send(embed=error_embed)

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

        choice = await route(self.bot, thread.guild, message.author, 'helper', opus="Opus" in tags)
        if choice is None:
            await storage_rpush(key, json.dumps(new_message))
            await storage_expire(key, REDIS_TTL)
            if should_notify(message.author.id):
                await message.reply(blocked_message(), mention_author=False, allowed_mentions=NO_PING)
            return

        history = normalize_history(limit_conversation(conversation))

        sent_msg = None
        try:
            sent_msg = await message.reply("⏳ Génération en cours...", mention_author=False, allowed_mentions=NO_PING)

            async def show_partial(text: str):
                await sent_msg.edit(content=text[:1990] + " ▌", allowed_mentions=NO_PING)

            reply = await stream_reply(
                choice, HELPER_SYSTEM, history, max_tokens=8192,
                user_id=message.author.id, feature='helper', on_text=show_partial,
            )

            answer, storable = finalize(reply)
            if choice.note:
                answer += f"\n\n-# {choice.note}"

            parts = split_text(answer, 2000)
            await sent_msg.edit(content=parts[0], allowed_mentions=NO_PING)
            for part in parts[1:]:
                await message.reply(part, mention_author=False, allowed_mentions=NO_PING)

        except Exception as e:
            logger.error(f"Erreur lors du traitement du message dans {thread.id}: {e}")
            error_text = friendly_error(e)
            if sent_msg:
                await sent_msg.edit(content=error_text)
            else:
                await message.reply(error_text, mention_author=False, allowed_mentions=NO_PING)
            return

        await storage_rpush(key, json.dumps(new_message))
        if storable:
            await storage_rpush(key, json.dumps({"role": "assistant", "content": reply.text.strip()}))
        await storage_expire(key, REDIS_TTL)

    @nextcord.slash_command(name="unindex", description="Supprime l'indexation du thread actuel dans Redis.")
    async def unindex_thread(self, interaction: nextcord.Interaction):
        if not await is_admin(self.bot, interaction.user):
            await interaction.response.send_message("Cette commande est réservée aux administrateurs.", ephemeral=True)
            return

        thread = interaction.channel
        if not isinstance(thread, nextcord.Thread) or thread.parent_id not in auto_reply_forum_ids:
            await interaction.response.send_message("Cette commande ne peut être utilisée que dans un thread autorisé.", ephemeral=True)
            return

        await storage_delete(f"thread:{thread.id}")
        await interaction.response.send_message("Indexation supprimée avec succès.", ephemeral=True)

    @nextcord.slash_command(name="debug_redis", description="Affiche le contenu brut des messages indexés dans Redis pour ce thread.")
    async def debug_redis(self, interaction: nextcord.Interaction, count: int = 10):
        if not await is_admin(self.bot, interaction.user):
            await interaction.response.send_message("Cette commande est réservée aux administrateurs.", ephemeral=True)
            return

        thread = interaction.channel
        if not isinstance(thread, nextcord.Thread) or thread.parent_id not in auto_reply_forum_ids:
            await interaction.response.send_message("Cette commande ne peut être utilisée que dans un thread autorisé.", ephemeral=True)
            return

        count = max(1, min(count, 20))
        messages = await storage_lrange(f"thread:{thread.id}", 0, count - 1)
        messages = [msg.decode('utf-8') for msg in messages]

        response_content = "\n".join(messages) if messages else "Aucun message indexé trouvé."
        if len(response_content) > 1900:
            response_content = response_content[:1900] + "…"
        await interaction.response.send_message(f"Contenu brut des messages indexés :\n{response_content}", ephemeral=True)


def setup(bot):
    bot.add_cog(AutoReply(bot))
