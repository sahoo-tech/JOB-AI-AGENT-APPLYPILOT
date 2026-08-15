"""
ApplyPilot — Persist API usage records to SQLite.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def log_api_usage(
    *,
    model: str,
    input_tokens: int,
    output_tokens: int,
    agent: str = "",
    action: str = "",
) -> None:
    """Insert one API usage record into the api_usage table."""
    try:
        con = sqlite3.connect(settings.db_path)
        con.execute(
            """
            INSERT INTO api_usage
                (timestamp, model, input_tokens, output_tokens, total_tokens, agent, action)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now(timezone.utc).isoformat(),
                model,
                input_tokens,
                output_tokens,
                input_tokens + output_tokens,
                agent,
                action,
            ),
        )
        con.commit()
        con.close()
    except Exception as exc:
        logger.warning("Failed to log API usage: %s", exc)
