"""
ApplyPilot — SQLite connection manager.
Call `init_db()` once at startup to create all tables.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)

_DDL = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS candidate_profile (
    id              INTEGER PRIMARY KEY,
    data            TEXT NOT NULL,          -- JSON blob of CandidateProfile
    updated_at      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cv_metadata (
    id                  INTEGER PRIMARY KEY,
    original_filename   TEXT NOT NULL,
    file_size           INTEGER NOT NULL,
    sha256              TEXT NOT NULL UNIQUE,
    storage_path        TEXT NOT NULL,
    import_timestamp    TEXT NOT NULL,
    is_master           INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id          TEXT PRIMARY KEY,
    company         TEXT,
    role            TEXT,
    location        TEXT,
    remote_status   TEXT,
    salary          TEXT,
    employment_type TEXT,
    experience_req  TEXT,
    education_req   TEXT,
    required_skills TEXT,       -- JSON array
    preferred_skills TEXT,      -- JSON array
    application_url TEXT,
    source          TEXT,
    deadline        TEXT,
    description     TEXT,
    description_hash TEXT,
    date_discovered TEXT,
    risk_level      TEXT,
    risk_reasons    TEXT        -- JSON array
);

CREATE TABLE IF NOT EXISTS job_scores (
    job_id              TEXT PRIMARY KEY,
    overall_score       REAL,
    skills_score        REAL,
    experience_score    REAL,
    education_score     REAL,
    role_score          REAL,
    location_score      REAL,
    preference_score    REAL,
    matched_skills      TEXT,   -- JSON array
    missing_skills      TEXT,   -- JSON array
    concerns            TEXT,   -- JSON array
    scored_at           TEXT
);

CREATE TABLE IF NOT EXISTS applications (
    id              TEXT PRIMARY KEY,
    company         TEXT,
    role            TEXT,
    application_url TEXT,
    source          TEXT,
    match_score     REAL,
    status          TEXT,
    date_discovered TEXT,
    date_started    TEXT,
    date_applied    TEXT,
    cv_filename     TEXT,
    cv_hash         TEXT,
    cover_letter    TEXT,
    answers         TEXT,       -- JSON
    notes           TEXT,
    last_updated    TEXT
);

CREATE TABLE IF NOT EXISTS interviews (
    id              TEXT PRIMARY KEY,
    application_id  TEXT,
    company         TEXT,
    role            TEXT,
    interview_date  TEXT,
    interview_time  TEXT,
    round           TEXT,
    interviewer     TEXT,
    meeting_url     TEXT,
    status          TEXT,
    notes           TEXT,
    FOREIGN KEY (application_id) REFERENCES applications(id)
);

CREATE TABLE IF NOT EXISTS api_usage (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,
    model           TEXT,
    input_tokens    INTEGER,
    output_tokens   INTEGER,
    total_tokens    INTEGER,
    agent           TEXT,
    action          TEXT
);

CREATE TABLE IF NOT EXISTS audit_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp           TEXT NOT NULL,
    agent               TEXT,
    action              TEXT,
    application_id      TEXT,
    company             TEXT,
    role                TEXT,
    model               TEXT,
    input_tokens        INTEGER,
    output_tokens       INTEGER,
    result              TEXT,
    error               TEXT,
    approval_required   INTEGER,
    approval_status     TEXT
);
"""


def init_db() -> None:
    """Create all tables (idempotent — safe to call on every startup)."""
    db_path: Path = settings.db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        con.executescript(_DDL)
        con.commit()
        logger.info("Database initialised at %s", db_path)
    finally:
        con.close()


@contextmanager
def get_connection() -> Generator[sqlite3.Connection, None, None]:
    """Context manager for a SQLite connection with row_factory."""
    con = sqlite3.connect(settings.db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
