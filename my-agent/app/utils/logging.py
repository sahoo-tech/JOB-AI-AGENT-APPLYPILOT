"""
ApplyPilot — Structured JSON audit logger.
Sensitive fields (passwords, API keys, cookies, tokens) are masked before writing.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.utils.config import settings

# ── Sensitive field masker ────────────────────────────────────────────────────
_SENSITIVE_KEYS = re.compile(
    r"(password|api[_-]?key|token|cookie|secret|oauth|session|credential|auth)",
    re.IGNORECASE,
)


def _mask(obj: Any, depth: int = 0) -> Any:
    """Recursively mask sensitive values in dicts."""
    if depth > 10:
        return obj
    if isinstance(obj, dict):
        return {
            k: "***MASKED***" if _SENSITIVE_KEYS.search(str(k)) else _mask(v, depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [_mask(i, depth + 1) for i in obj]
    return obj


# ── Audit log file ────────────────────────────────────────────────────────────
def _audit_log_path() -> Path:
    settings.logs_dir.mkdir(parents=True, exist_ok=True)
    return settings.logs_dir / "audit.jsonl"


def write_audit(
    *,
    agent: str,
    action: str,
    application_id: str | None = None,
    company: str | None = None,
    role: str | None = None,
    model: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    result: str | None = None,
    error: str | None = None,
    approval_required: bool = False,
    approval_status: str | None = None,
    extra: dict | None = None,
) -> None:
    """Append one JSON line to audit.jsonl."""
    record: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "agent": agent,
        "action": action,
        "application_id": application_id,
        "company": company,
        "role": role,
        "model": model,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "result": result,
        "error": error,
        "approval_required": approval_required,
        "approval_status": approval_status,
    }
    if extra:
        record["extra"] = _mask(extra)

    try:
        with _audit_log_path().open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record) + "\n")
    except Exception as exc:  # never crash the agent just because logging failed
        logging.getLogger(__name__).warning("Audit log write failed: %s", exc)


# ── Standard Python logger ────────────────────────────────────────────────────
def get_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger
