"""Couche Anthropic partagée : client, routage modèle/budget, streaming, coût, erreurs, texte.

Le préfixe `_` empêche le chargeur de modules de le traiter comme une extension Discord.
"""
import base64
import logging
import os
import time
from dataclasses import dataclass

import anthropic
import nextcord

from . import _usage

logger = logging.getLogger('bot.claude')

if not os.getenv('ANTHROPIC_API_KEY'):
    raise EnvironmentError("La clé API 'ANTHROPIC_API_KEY' doit être définie.")

# Un seul client partagé ; le timeout reste sous les 15 min de validité d'un token d'interaction Discord.
client = anthropic.AsyncAnthropic(timeout=120.0, max_retries=2)

NO_PING = nextcord.AllowedMentions.none()


def env_ids(name: str) -> set[int]:
    return {int(x) for x in os.getenv(name, '').split(',') if x.strip().isdigit()}


# --- Modèles, effort, prix ---------------------------------------------------

# tier -> (identifiant du modèle, $ / 1M tokens en entrée, $ / 1M tokens en sortie)
# ponytail: Haiku 5.5 double au-delà de 100K tokens de prompt, non modélisé (le contexte reste très en dessous).
TIERS = {
    'haiku':  (os.getenv('CLAUDE_MODEL_HAIKU') or 'claude-haiku-5-5', 0.10, 0.50),
    'sonnet': (os.getenv('CLAUDE_MODEL_SONNET') or 'claude-sonnet-5-5', 2.0, 10.0),
    'opus':   (os.getenv('CLAUDE_MODEL_OPUS') or 'claude-opus-5-5', 4.0, 20.0),
}

# fonctionnalité -> (tier, effort)
PROFILES = {
    'forum':  ('sonnet', 'medium'),   # réponse automatique à un nouveau post
    'ask':    ('haiku', 'low'),       # /ask-gpt
    'helper': ('sonnet', 'low'),      # suite de conversation GPT-Helper
    'resume': ('haiku', 'low'),       # /resume
    'opus':   ('opus', 'medium'),     # tag « Opus » (réservé à certains rôles)
}

# Beta : le serveur relance la requête sur un autre modèle si le classifieur de sécurité refuse.
# Pas de fallback serveur sur Haiku.
FALLBACK_BETA = 'server-side-fallback-2026-07-01'

SOFT_USD = float(os.getenv('BUDGET_SOFT_USD', '5'))   # au-delà : Haiku low pour tout
HARD_USD = float(os.getenv('BUDGET_HARD_USD', '8'))   # au-delà : plus de réponse
OPUS_ROLE_IDS = env_ids('OPUS_ROLE_IDS')
ADMIN_ROLE_IDS = env_ids('ADMIN_ROLE_IDS')

BASE_PERSONA = (
    "Tu es un expert en informatique nommé iBot-GPT. "
    "Si tu reçois une question qui ne concerne pas ce domaine, n'hésite pas à rappeler à l'utilisateur "
    "que ce serveur est axé sur l'informatique. "
    "Assure-toi toujours de t'adresser en tutoyant l'utilisateur. "
    "Pour améliorer la lisibilité, utilise le markdown compatible embed Discord "
    "(gras, italique, listes, blocs de code ; pas de tableaux)."
)


@dataclass
class Choice:
    tier: str
    effort: str
    note: str | None = None   # explication affichée à l'utilisateur quand on s'écarte de son choix

    @property
    def model(self) -> str:
        return TIERS[self.tier][0]


async def _role_ids(guild, user) -> set[int]:
    member = user if hasattr(user, 'roles') else None
    if member is None and guild is not None:
        try:
            member = guild.get_member(user.id) or await guild.fetch_member(user.id)
        except nextcord.HTTPException:
            return set()
    return {r.id for r in member.roles} if member else set()


async def is_admin(bot, user) -> bool:
    return await bot.is_owner(user) or bool(ADMIN_ROLE_IDS & {r.id for r in getattr(user, 'roles', [])})


async def route(bot, guild, user, feature: str, opus: bool = False) -> Choice | None:
    """Choisit modèle et effort pour `user`. Renvoie None si son budget du mois est épuisé.

    Le créateur du bot n'a aucune limite. Les autres : Opus réservé à OPUS_ROLE_IDS (repli sur le
    profil de la fonctionnalité), puis au-delà de SOFT_USD tout passe en Haiku low, au-delà de
    HARD_USD plus aucune réponse.
    """
    if await bot.is_owner(user):
        return Choice(*PROFILES['opus' if opus else feature])

    tier, effort = PROFILES[feature]
    note = None
    if opus:
        if OPUS_ROLE_IDS & await _role_ids(guild, user):
            tier, effort = PROFILES['opus']
        else:
            note = "Opus est réservé à certains rôles : réponse générée avec Sonnet."

    spent = _usage.month_spend(user.id)
    if spent >= HARD_USD:
        return None
    if spent >= SOFT_USD and tier != 'haiku':
        tier, effort = 'haiku', 'low'
        note = f"Budget mensuel de {SOFT_USD:g} $ dépassé : réponses en mode économique (Haiku)."
    return Choice(tier, effort, note)


def blocked_message() -> str:
    return (f"Tu as utilisé tout ton budget IA du mois ({HARD_USD:g} $). "
            "Il sera remis à zéro le 1er du mois prochain.")


_last_notice: dict[int, float] = {}


def should_notify(user_id: int, every: float = 3600.0) -> bool:
    """Évite de répéter le message « budget épuisé » à chaque message de l'utilisateur."""
    now = time.monotonic()
    if now - _last_notice.get(user_id, float('-inf')) < every:
        return False
    _last_notice[user_id] = now
    return True


# --- Appel et streaming ------------------------------------------------------

@dataclass
class Reply:
    text: str
    stop_reason: str | None
    input_tokens: int
    output_tokens: int
    cost: float


async def stream_reply(choice: Choice, system: str, messages: list[dict], max_tokens: int,
                       user_id: int, feature: str, on_text=None, interval: float = 1.0) -> Reply:
    """Génère une réponse en streaming et enregistre l'usage dans SQLite.

    `on_text(texte_partiel)` est attendu au plus une fois par `interval` secondes.
    """
    kwargs = dict(model=choice.model, max_tokens=max_tokens, system=system, messages=messages,
                  output_config={'effort': choice.effort})
    if choice.tier == 'haiku':
        manager = client.messages.stream(**kwargs)
    else:
        manager = client.beta.messages.stream(betas=[FALLBACK_BETA], fallbacks='default', **kwargs)

    partial, last = '', time.monotonic()
    async with manager as stream:
        async for delta in stream.text_stream:
            partial += delta
            now = time.monotonic()
            if on_text and now - last >= interval:
                last = now
                try:
                    await on_text(partial)
                except Exception:
                    pass  # édition Discord ratée : sans importance
        final = await stream.get_final_message()

    text = ''.join(b.text for b in final.content if b.type == 'text')
    usage = final.usage
    # ponytail: prix du tier demandé ; si le fallback serveur a répondu, le coût réel peut différer.
    _, price_in, price_out = TIERS[choice.tier]
    cost = (usage.input_tokens * price_in + usage.output_tokens * price_out) / 1_000_000
    _usage.log_usage(user_id, feature, final.model, choice.effort, usage.input_tokens, usage.output_tokens, cost)
    if final.stop_reason == 'refusal':
        logger.warning(f"Refus ({getattr(final.stop_details, 'category', None)}) pour {feature}, user {user_id}")
    return Reply(text, final.stop_reason, usage.input_tokens, usage.output_tokens, cost)


def finalize(reply: Reply) -> tuple[str, bool]:
    """Texte à afficher, et si la réponse mérite d'être stockée dans l'historique."""
    if reply.stop_reason == 'refusal':
        return "Je ne peux pas répondre à cette demande.", False
    text = reply.text.strip()
    if not text:
        return "Je n'ai pas pu générer de réponse. Réessaie en reformulant.", False
    if reply.stop_reason == 'max_tokens':
        text += "\n\n*(réponse tronquée)*"
    return text, True


def friendly_error(e: Exception) -> str:
    logger.error(f"Erreur API Anthropic (request-id={getattr(e, 'request_id', None)}): {e}", exc_info=True)
    if isinstance(e, anthropic.RateLimitError):
        return "Trop de demandes en ce moment, réessaie dans un instant."
    if isinstance(e, anthropic.APIConnectionError) or (
            isinstance(e, anthropic.APIStatusError) and e.status_code >= 500):
        return "Le service d'IA est indisponible ou surchargé, réessaie plus tard."
    return "Une erreur s'est produite lors de la génération de la réponse."


# --- Texte, historique, images -----------------------------------------------

def split_text(text: str, max_length: int = 4000) -> list[str]:
    """Découpe sur les sauts de ligne ; une ligne plus longue que `max_length` est coupée net."""
    parts, cur = [], ''
    for line in text.split('\n'):
        while len(line) > max_length:
            if cur:
                parts.append(cur)
                cur = ''
            parts.append(line[:max_length])
            line = line[max_length:]
        if cur and len(cur) + len(line) + 1 > max_length:
            parts.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return [p.rstrip() for p in parts if p.strip()] or ['']


def normalize_history(history: list[dict]) -> list[dict]:
    """Rend un historique stocké valide pour l'API : user/assistant seulement, non vides,
    qui commence par `user`, rôles consécutifs fusionnés (anciens messages `system` ignorés)."""
    out: list[dict] = []
    for m in history:
        role, content = m.get('role'), str(m.get('content', '')).strip()
        if role not in ('user', 'assistant') or not content:
            continue
        if out and out[-1]['role'] == role:
            out[-1]['content'] += f"\n\n{content}"
        elif out or role == 'user':
            out.append({'role': role, 'content': content})
    return out


IMAGE_TYPES = {'image/png', 'image/jpeg', 'image/gif', 'image/webp'}
MAX_IMAGES = 5
MAX_IMAGE_BYTES = 4_000_000   # 5 images en base64 restent sous les 32 Mo par requête


async def image_blocks(attachments, limit: int = MAX_IMAGES) -> tuple[list[dict], list[str]]:
    """(blocs image base64 pour l'API, noms des pièces jointes non analysées)."""
    blocks, skipped = [], []
    for a in attachments:
        if a.content_type in IMAGE_TYPES and a.size <= MAX_IMAGE_BYTES and len(blocks) < limit:
            try:
                data = base64.standard_b64encode(await a.read()).decode()
            except nextcord.HTTPException:
                skipped.append(a.filename)
                continue
            blocks.append({'type': 'image', 'source': {'type': 'base64', 'media_type': a.content_type, 'data': data}})
        else:
            skipped.append(a.filename)
    return blocks, skipped
