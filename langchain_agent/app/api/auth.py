"""Bearer token authentication with admin master key + persistent token pool.

- ``ATLAS_API_TOKEN`` in ``.env`` is the **admin master key** (never expires).
  Use it to generate one-time tokens and for admin operations.
- One-time tokens are generated via ``POST /auth/tokens?count=N`` and stored
  in SQLite so they **survive server restarts**.
- On logout the token is consumed (deleted from DB).
- When the env var is **empty** (local dev), auth is disabled entirely.
"""

from __future__ import annotations

import logging
import os
import secrets
import sqlite3
import string
import time

from fastapi import HTTPException, Request, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import get_settings

logger = logging.getLogger(__name__)

_bearer_scheme = HTTPBearer(auto_error=False)

# ── Token pool (SQLite-backed) ────────────────────────────────────────────
_master_key: str | None = None
_db_conn: sqlite3.Connection | None = None
DEFAULT_USER_ID = "default-user"
ADMIN_USER_ID = "admin-atlas"


def _get_master_key() -> str:
    global _master_key
    if _master_key is None:
        _master_key = get_settings().api_token or ""
    return _master_key


def _get_db() -> sqlite3.Connection:
    """Return (and lazily create) the SQLite connection for the token pool."""
    global _db_conn
    if _db_conn is not None:
        return _db_conn
    settings = get_settings()
    db_path = settings.checkpoint_db_path
    if db_path == ":memory:":
        db_path = os.path.join(str(settings.cache_dir), "tokens.db")
    db_dir = os.path.dirname(db_path)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    _db_conn = sqlite3.connect(db_path)
    _db_conn.execute("PRAGMA journal_mode=WAL")
    _db_conn.execute("""
        CREATE TABLE IF NOT EXISTS token_pool (
            token      TEXT PRIMARY KEY,
            created_at REAL NOT NULL,
            consumed   INTEGER DEFAULT 0,
            user_id    TEXT NOT NULL DEFAULT ''
        )
    """)
    # Migrate: add user_id column if missing (existing DBs)
    try:
        _db_conn.execute("ALTER TABLE token_pool ADD COLUMN user_id TEXT NOT NULL DEFAULT ''")
    except Exception:
        pass  # column already exists
    _db_conn.commit()
    logger.info("Token pool DB initialised at %s", db_path)
    return _db_conn


def _generate_token(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_tokens(count: int = 1, *, user_id: str = "") -> list[str]:
    """Generate *count* one-time tokens and persist to DB.

    If *user_id* is provided, the tokens will always resolve to that
    user_id even after a server restart.
    """
    db = _get_db()
    tokens = [_generate_token() for _ in range(count)]
    now = time.time()
    db.executemany(
        "INSERT OR IGNORE INTO token_pool (token, created_at, user_id) VALUES (?, ?, ?)",
        [(t, now, user_id) for t in tokens],
    )
    db.commit()
    for t in tokens:
        logger.info("New one-time token: %s (user_id=%s)", t, user_id or "(none)")
    return tokens


def consume_token(token: str) -> bool:
    """Mark a one-time token as consumed (delete from DB)."""
    db = _get_db()
    cur = db.execute("DELETE FROM token_pool WHERE token = ? AND consumed = 0", (token,))
    db.commit()
    consumed = cur.rowcount > 0
    if consumed:
        logger.info("Token consumed: %s...", token[:6])
    return consumed


def get_pool_status() -> dict:
    """Return pool stats for admin."""
    db = _get_db()
    rows = db.execute("SELECT token FROM token_pool WHERE consumed = 0").fetchall()
    tokens = [r[0] for r in rows]
    return {
        "available": len(tokens),
        "tokens": sorted(tokens),
    }


def is_admin_token(token: str | None) -> bool:
    """Return True when the supplied token matches the admin master key."""
    master = _get_master_key()
    return bool(master and token and token == master)


def is_valid_token(token: str) -> bool:
    """Check if a token is the master key or a valid pool token."""
    master = _get_master_key()
    if not master:
        return True  # auth disabled
    if token == master:
        return True
    db = _get_db()
    row = db.execute(
        "SELECT 1 FROM token_pool WHERE token = ? AND consumed = 0", (token,)
    ).fetchone()
    return row is not None


def _is_localhost(request: Request) -> bool:
    """Return True when the request originates from loopback."""
    client = request.client
    if client and client.host in ("127.0.0.1", "::1", "0.0.0.0", "localhost"):
        return True
    return False


async def verify_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """FastAPI dependency — raises 401 if the token is missing / wrong."""
    master = _get_master_key()
    if not master:
        return  # auth disabled — pass through

    if credentials is None or not is_valid_token(credentials.credentials):
        logger.warning("Rejected request: invalid or missing Bearer token")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API token",
            headers={"WWW-Authenticate": "Bearer"},
        )


def _hash_token(token: str) -> str:
    """Derive a stable, non-reversible user_id from a Bearer token."""
    import hashlib
    return hashlib.sha256(token.encode()).hexdigest()[:16]


def resolve_user_id_from_token(token: str | None) -> str:
    """Resolve the persisted user_id associated with a Bearer token.

    For the admin master key → returns the fixed ``ADMIN_USER_ID``.
    For pool tokens → looks up the ``user_id`` column persisted at creation.
    Falls back to ``_hash_token(token)`` for tokens without a stored user_id.
    """
    if not token:
        return DEFAULT_USER_ID
    # Admin master key → fixed stable user_id
    if is_admin_token(token):
        return ADMIN_USER_ID
    # Pool token → look up persisted user_id
    db = _get_db()
    row = db.execute(
        "SELECT user_id FROM token_pool WHERE token = ?",
        (token,),
    ).fetchone()
    if row and row[0]:
        return row[0]
    # Fallback: derive from hash (legacy tokens)
    return _hash_token(token)


async def get_current_user_id(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> str:
    """FastAPI dependency — return a stable user_id derived from the Bearer token.

    - Admin master key → ``ADMIN_USER_ID`` (fixed, survives restarts)
    - Pool / LLM tokens → ``user_id`` persisted in token_pool at creation
    - No auth → ``DEFAULT_USER_ID``
    """
    if credentials and credentials.credentials:
        return resolve_user_id_from_token(credentials.credentials)
    return DEFAULT_USER_ID
