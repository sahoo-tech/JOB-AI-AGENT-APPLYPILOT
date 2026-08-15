"""
ApplyPilot — CRUD repositories for all data models.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.storage.database import get_connection
from app.storage.models import (
    Application,
    CandidateProfile,
    Job,
    JobMatchScore,
    InterviewRecord,
    VALID_TRANSITIONS,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Profile Repository ────────────────────────────────────────────────────────

class ProfileRepository:
    @staticmethod
    def save(profile: CandidateProfile) -> None:
        import dataclasses
        data = json.dumps(dataclasses.asdict(profile))
        with get_connection() as con:
            existing = con.execute("SELECT id FROM candidate_profile LIMIT 1").fetchone()
            if existing:
                con.execute(
                    "UPDATE candidate_profile SET data=?, updated_at=? WHERE id=?",
                    (data, _now(), existing["id"]),
                )
            else:
                con.execute(
                    "INSERT INTO candidate_profile (data, updated_at) VALUES (?, ?)",
                    (data, _now()),
                )

    @staticmethod
    def load() -> Optional[CandidateProfile]:
        with get_connection() as con:
            row = con.execute("SELECT data FROM candidate_profile LIMIT 1").fetchone()
            if not row:
                return None
            import dataclasses
            data = json.loads(row["data"])
            profile = CandidateProfile()
            for k, v in data.items():
                if hasattr(profile, k):
                    setattr(profile, k, v)
            return profile


# ── Job Repository ────────────────────────────────────────────────────────────

class JobRepository:
    @staticmethod
    def upsert(job: Job) -> None:
        with get_connection() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO jobs (
                    job_id, company, role, location, remote_status, salary,
                    employment_type, experience_req, education_req,
                    required_skills, preferred_skills, application_url, source,
                    deadline, description, description_hash, date_discovered,
                    risk_level, risk_reasons
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    job.job_id, job.company, job.role, job.location,
                    job.remote_status, job.salary, job.employment_type,
                    job.experience_required, job.education_required,
                    json.dumps(job.required_skills),
                    json.dumps(job.preferred_skills),
                    job.application_url, job.source, job.deadline,
                    job.description, job.description_hash, job.date_discovered,
                    job.risk_level, json.dumps(job.risk_reasons),
                ),
            )

    @staticmethod
    def get(job_id: str) -> Optional[Job]:
        with get_connection() as con:
            row = con.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            if not row:
                return None
            return _row_to_job(row)

    @staticmethod
    def all_jobs() -> list[Job]:
        with get_connection() as con:
            rows = con.execute("SELECT * FROM jobs ORDER BY date_discovered DESC").fetchall()
            return [_row_to_job(r) for r in rows]

    @staticmethod
    def exists_by_hash(description_hash: str) -> bool:
        with get_connection() as con:
            row = con.execute(
                "SELECT 1 FROM jobs WHERE description_hash=?", (description_hash,)
            ).fetchone()
            return row is not None

    @staticmethod
    def save_score(score: JobMatchScore) -> None:
        with get_connection() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO job_scores (
                    job_id, overall_score, skills_score, experience_score,
                    education_score, role_score, location_score, preference_score,
                    matched_skills, missing_skills, concerns, scored_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    score.job_id, score.overall_score, score.skills_score,
                    score.experience_score, score.education_score,
                    score.role_score, score.location_score, score.preference_score,
                    json.dumps(score.matched_skills), json.dumps(score.missing_skills),
                    json.dumps(score.concerns), _now(),
                ),
            )


def _row_to_job(row) -> Job:
    j = Job()
    j.job_id = row["job_id"]
    j.company = row["company"] or ""
    j.role = row["role"] or ""
    j.location = row["location"] or ""
    j.remote_status = row["remote_status"] or "UNKNOWN"
    j.salary = row["salary"] or "UNKNOWN"
    j.employment_type = row["employment_type"] or "UNKNOWN"
    j.experience_required = row["experience_req"] or "UNKNOWN"
    j.education_required = row["education_req"] or "UNKNOWN"
    j.required_skills = json.loads(row["required_skills"] or "[]")
    j.preferred_skills = json.loads(row["preferred_skills"] or "[]")
    j.application_url = row["application_url"] or ""
    j.source = row["source"] or ""
    j.deadline = row["deadline"] or "UNKNOWN"
    j.description = row["description"] or ""
    j.description_hash = row["description_hash"] or ""
    j.date_discovered = row["date_discovered"] or ""
    j.risk_level = row["risk_level"] or "UNKNOWN"
    j.risk_reasons = json.loads(row["risk_reasons"] or "[]")
    return j


# ── Application Repository ────────────────────────────────────────────────────

class ApplicationRepository:
    @staticmethod
    def create(company: str, role: str, url: str, source: str, match_score: float) -> Application:
        app_id = f"APP-{uuid.uuid4().hex[:6].upper()}"
        now = _now()
        app = Application(
            id=app_id,
            company=company,
            role=role,
            application_url=url,
            source=source,
            match_score=match_score,
            status="DISCOVERED",
            date_discovered=now,
            last_updated=now,
        )
        with get_connection() as con:
            con.execute(
                """
                INSERT INTO applications (
                    id, company, role, application_url, source, match_score,
                    status, date_discovered, date_started, date_applied,
                    cv_filename, cv_hash, cover_letter, answers, notes, last_updated
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    app.id, app.company, app.role, app.application_url,
                    app.source, app.match_score, app.status,
                    app.date_discovered, "", "", "", "", "", "", "", app.last_updated,
                ),
            )
        return app

    @staticmethod
    def get(app_id: str) -> Optional[Application]:
        with get_connection() as con:
            row = con.execute(
                "SELECT * FROM applications WHERE id=?", (app_id,)
            ).fetchone()
            if not row:
                return None
            return _row_to_app(row)

    @staticmethod
    def transition(app_id: str, new_status: str) -> Application:
        """
        Move application to new_status.
        Raises ValueError for illegal transitions (enforced at Python layer).
        """
        app = ApplicationRepository.get(app_id)
        if app is None:
            raise ValueError(f"Application {app_id} not found")
        allowed = VALID_TRANSITIONS.get(app.status, [])
        if new_status not in allowed:
            raise ValueError(
                f"Illegal state transition {app.status} → {new_status} "
                f"for application {app_id}. Allowed: {allowed}"
            )
        now = _now()
        extra = {}
        if new_status == "IN_PROGRESS":
            extra["date_started"] = now
        if new_status == "SUBMITTED":
            extra["date_applied"] = now

        set_clause = "status=?, last_updated=?"
        params: list = [new_status, now]
        for col, val in extra.items():
            set_clause += f", {col}=?"
            params.append(val)
        params.append(app_id)

        with get_connection() as con:
            con.execute(f"UPDATE applications SET {set_clause} WHERE id=?", params)

        app.status = new_status
        app.last_updated = now
        return app

    @staticmethod
    def update_cv(app_id: str, cv_filename: str, cv_hash: str) -> None:
        with get_connection() as con:
            con.execute(
                "UPDATE applications SET cv_filename=?, cv_hash=?, last_updated=? WHERE id=?",
                (cv_filename, cv_hash, _now(), app_id),
            )

    @staticmethod
    def update_cover_letter(app_id: str, cover_letter: str) -> None:
        with get_connection() as con:
            con.execute(
                "UPDATE applications SET cover_letter=?, last_updated=? WHERE id=?",
                (cover_letter, _now(), app_id),
            )

    @staticmethod
    def update_answers(app_id: str, answers: dict) -> None:
        with get_connection() as con:
            con.execute(
                "UPDATE applications SET answers=?, last_updated=? WHERE id=?",
                (json.dumps(answers), _now(), app_id),
            )

    @staticmethod
    def is_duplicate(company: str, role: str, url: str) -> bool:
        """True if an active application already exists for this company+role+url."""
        norm_role = role.lower().strip()
        with get_connection() as con:
            row = con.execute(
                """
                SELECT 1 FROM applications
                WHERE lower(company)=? AND lower(role)=? AND application_url=?
                  AND status NOT IN ('REJECTED','WITHDRAWN')
                LIMIT 1
                """,
                (company.lower().strip(), norm_role, url),
            ).fetchone()
            return row is not None

    @staticmethod
    def all_applications() -> list[Application]:
        with get_connection() as con:
            rows = con.execute(
                "SELECT * FROM applications ORDER BY last_updated DESC"
            ).fetchall()
            return [_row_to_app(r) for r in rows]


def _row_to_app(row) -> Application:
    a = Application()
    for col in Application.__dataclass_fields__:
        val = row[col] if col in row.keys() else None
        if val is not None:
            setattr(a, col, val)
    return a


# ── Interview Repository ───────────────────────────────────────────────────────

class InterviewRepository:
    @staticmethod
    def create(interview: InterviewRecord) -> InterviewRecord:
        if not interview.id:
            interview.id = f"INT-{uuid.uuid4().hex[:6].upper()}"
        with get_connection() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO interviews (
                    id, application_id, company, role, interview_date,
                    interview_time, round, interviewer, meeting_url, status, notes
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    interview.id, interview.application_id, interview.company,
                    interview.role, interview.interview_date, interview.interview_time,
                    interview.round, interview.interviewer, interview.meeting_url,
                    interview.status, interview.notes,
                ),
            )
        return interview

    @staticmethod
    def for_application(application_id: str) -> list[InterviewRecord]:
        with get_connection() as con:
            rows = con.execute(
                "SELECT * FROM interviews WHERE application_id=?", (application_id,)
            ).fetchall()
            return [_row_to_interview(r) for r in rows]


def _row_to_interview(row) -> InterviewRecord:
    i = InterviewRecord()
    for col in InterviewRecord.__dataclass_fields__:
        val = row[col] if col in row.keys() else None
        if val is not None:
            setattr(i, col, val)
    return i
