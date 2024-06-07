import nextcord
from nextcord.ext import commands
import os
import logging
import asyncio

# Configuration du logger
logger = logging.getLogger('bot.tag_logger_module')

# Variables d'environnement pour la configuration
auto_reply_forum_ids_str = os.getenv('AUTO_REPLY_FORUM_IDS', '')

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

class TagLogger(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_thread_create(self, thread: nextcord.Thread):
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
        tags = thread.applied_tags  # Récupérer les tags appliqués au thread

        if tags:
            tag_names = ", ".join(tag.name for tag in tags)
            logger.info(f"Thread créé par {user_name} (ID: {base_message.author.id}) avec le(s) tag(s) : {tag_names}")
        else:
            logger.info(f"Thread créé par {user_name} (ID: {base_message.author.id}) sans tags applicables.")

def setup(bot):
    bot.add_cog(TagLogger(bot))
