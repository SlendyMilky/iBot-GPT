"""Journal SQLite des appels à l'API : une ligne par appel, budget mensuel par utilisateur."""
import os
import sqlite3
from datetime import datetime

DB_PATH = os.getenv('USAGE_DB_PATH', 'data/usage.db')

_db: sqlite3.Connection | None = None


def _conn() -> sqlite3.Connection:
    # ponytail: sqlite synchrone dans la boucle d'événements (écritures de l'ordre de la ms),
    # passer par asyncio.to_thread si le débit devient un problème.
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DB_PATH) or '.', exist_ok=True)
        _db = sqlite3.connect(DB_PATH, isolation_level=None)  # autocommit
        _db.execute(
            "CREATE TABLE IF NOT EXISTS usage ("
            "ts TEXT NOT NULL, user_id INTEGER NOT NULL, feature TEXT NOT NULL, "
            "model TEXT NOT NULL, effort TEXT, input_tokens INTEGER NOT NULL, "
            "output_tokens INTEGER NOT NULL, cost_usd REAL NOT NULL)"
        )
        _db.execute("CREATE INDEX IF NOT EXISTS usage_user_ts ON usage (user_id, ts)")
    return _db


def month_key() -> str:
    """Mois calendaire courant (heure locale du conteneur), ex. '2026-10'."""
    return datetime.now().strftime('%Y-%m')


def log_usage(user_id: int, feature: str, model: str, effort: str,
              input_tokens: int, output_tokens: int, cost_usd: float) -> None:
    _conn().execute(
        "INSERT INTO usage VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (datetime.now().strftime('%Y-%m-%d %H:%M:%S'), user_id, feature, model, effort,
         input_tokens, output_tokens, cost_usd),
    )


def month_spend(user_id: int, month: str | None = None) -> float:
    row = _conn().execute(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM usage WHERE user_id = ? AND substr(ts, 1, 7) = ?",
        (user_id, month or month_key()),
    ).fetchone()
    return row[0]


def month_breakdown(user_id: int, month: str | None = None) -> list[tuple]:
    """[(model, appels, tokens_entrée, tokens_sortie, coût)] du mois, le plus coûteux en premier."""
    return _conn().execute(
        "SELECT model, COUNT(*), SUM(input_tokens), SUM(output_tokens), SUM(cost_usd) "
        "FROM usage WHERE user_id = ? AND substr(ts, 1, 7) = ? "
        "GROUP BY model ORDER BY SUM(cost_usd) DESC",
        (user_id, month or month_key()),
    ).fetchall()
