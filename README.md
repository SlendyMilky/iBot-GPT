# iBot-GPT 🤖🔧

Bot Discord d'assistance informatique propulsé par l'API Anthropic (Claude).

## Fonctionnalités 🚀

- **Réponse automatique** à chaque nouveau post d'un forum configuré (images comprises).
- **GPT-Helper** : un thread du forum portant le tag `GPT-Helper` devient une conversation suivie, dont l'historique est conservé dans Redis (30 jours).
- **`/ask-gpt`** : question rapide.
- **`/resume`** : résumé des derniers messages d'un salon (rôles autorisés).
- **`/usage`** : consommation IA du mois (la tienne ; celle d'un membre pour les admins).
- **`/unindex`, `/debug_redis`** : gestion de l'historique d'un thread (admins).

## Modèles et budget 💸

| Usage | Modèle | Effort |
|---|---|---|
| Réponse automatique du forum | Sonnet 5.5 | medium |
| GPT-Helper (suite de conversation) | Sonnet 5.5 | low |
| `/ask-gpt`, `/resume` | Haiku 5.5 | low |
| Tag de forum `Opus` (rôles `OPUS_ROLE_IDS` uniquement) | Opus 5.5 | medium |

Chaque utilisateur a un budget **mensuel** (mois calendaire) :

- jusqu'à `BUDGET_SOFT_USD` (5 $) : routage ci-dessus ;
- au-delà : tout passe en Haiku (effort low) ;
- au-delà de `BUDGET_HARD_USD` (8 $) : le bot ne répond plus à cet utilisateur, qui en est averti.

Le créateur du bot (propriétaire de l'application Discord) n'a aucune limite. Chaque appel est enregistré dans une base SQLite (`USAGE_DB_PATH`) : utilisateur, fonctionnalité, modèle, tokens et coût. Aucun contenu de message n'y est stocké. Les coûts affichés sont des estimations.

## Tags de forum 🏷️

- `No GPT` : le bot ignore le post.
- `GPT-Helper` : mode conversation.
- `Opus` : demande Opus (repli sur Sonnet pour les membres sans rôle autorisé).

## Prérequis 🧾

- Python ≥ 3.10 (ou Docker).
- Une clé API Anthropic et un token de bot Discord (intent « Message Content » activé).
- Redis, sauf `REDIS_ENABLED=false` (historique GPT-Helper alors en mémoire, non persistant).

## Variables d'environnement 🔐

Voir [`.env.example`](.env.example) pour la liste complète.

| Variable | Rôle |
|---|---|
| `ANTHROPIC_API_KEY`, `BOT_TOKEN` | Clés (obligatoires) |
| `CLAUDE_MODEL_HAIKU` / `_SONNET` / `_OPUS` | Identifiants de modèles |
| `AUTO_REPLY_FORUM_IDS` | Forums gérés par le bot |
| `OPUS_ROLE_IDS` | Rôles autorisés à utiliser Opus |
| `ADMIN_ROLE_IDS` | Rôles admin (`/usage` d'un autre membre, `/unindex`, `/debug_redis`) |
| `BUDGET_SOFT_USD`, `BUDGET_HARD_USD` | Seuils mensuels par utilisateur |
| `USAGE_DB_PATH` | Fichier SQLite des usages (`data/usage.db`) |
| `ASK_GPT_UNAUTHORIZED_ROLE_IDS`, `RESUME_AUTHORIZED_ROLE_IDS`, `RESUME_LOG_CHANNEL_ID` | Accès à `/ask-gpt` et `/resume` |
| `REDIS_ENABLED`, `REDIS_HOST`, `REDIS_PORT` | Redis |

## Lancer le bot ▶️

```bash
pip install -r requirements.txt
cp .env.example .env   # puis renseigner les valeurs
python ibot-gpt.py
```

## Docker 🐳

```yaml
services:
    ibot-gpt:
        image: 'ghcr.io/slendymilky/ibot-gpt:3.0.0'
        container_name: ibot-gpt
        restart: always
        env_file: stack.env
        volumes:
            - ./data:/iBot/data   # base SQLite des usages
```

Redis doit être joignable via `REDIS_HOST` (il n'est pas fourni par ce compose).

## Tests 🧪

```bash
python tests/test_core.py
```

## Logging 📚

Les journaux sont écrits sur la sortie standard et dans `bot_log.txt`.

---

**Remarque** : projet conçu pour un serveur communautaire, pas un centre d'aide professionnel. Les messages (et images) traités par le bot sont envoyés à Anthropic.

Si vous avez des questions ou des améliorations, n'hésitez pas à ouvrir une issue ou une pull request.
