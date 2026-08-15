"""
ApplyPilot — Data models (dataclasses / TypedDicts).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


# ── Candidate Profile ─────────────────────────────────────────────────────────

@dataclass
class Education:
    institution: str = ""
    degree: str = ""
    field_of_study: str = ""
    start_year: Optional[int] = None
    end_year: Optional[int] = None
    grade: str = ""


@dataclass
class Experience:
    company: str = ""
    title: str = ""
    location: str = ""
    start_date: str = ""
    end_date: str = ""
    responsibilities: list[str] = field(default_factory=list)
    is_internship: bool = False


@dataclass
class Project:
    name: str = ""
    description: str = ""
    technologies: list[str] = field(default_factory=list)
    url: str = ""


@dataclass
class Certification:
    name: str = ""
    issuer: str = ""
    date: str = ""
    url: str = ""


@dataclass
class CandidateProfile:
    full_name: str = ""
    email: str = ""
    phone: str = ""
    location: str = ""

    education: list[Education] = field(default_factory=list)
    experience: list[Experience] = field(default_factory=list)
    internships: list[Experience] = field(default_factory=list)
    projects: list[Project] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    certifications: list[Certification] = field(default_factory=list)
    achievements: list[str] = field(default_factory=list)

    github: str = ""
    linkedin: str = ""
    portfolio: str = ""

    preferred_roles: list[str] = field(default_factory=list)
    preferred_locations: list[str] = field(default_factory=list)
    remote_preference: str = "any"          # remote | hybrid | on-site | any
    minimum_salary: Optional[int] = None
    employment_preferences: list[str] = field(default_factory=list)  # full-time, internship …

    # CV file info
    master_cv_path: str = ""
    master_cv_hash: str = ""
    master_cv_original_filename: str = ""
    master_cv_size: int = 0
    master_cv_import_timestamp: str = ""


# ── Job ───────────────────────────────────────────────────────────────────────

@dataclass
class Job:
    job_id: str = ""
    company: str = ""
    role: str = ""
    location: str = ""
    remote_status: str = "UNKNOWN"
    salary: str = "UNKNOWN"
    employment_type: str = "UNKNOWN"
    experience_required: str = "UNKNOWN"
    education_required: str = "UNKNOWN"
    required_skills: list[str] = field(default_factory=list)
    preferred_skills: list[str] = field(default_factory=list)
    application_url: str = ""
    source: str = ""
    deadline: str = "UNKNOWN"
    description: str = ""
    description_hash: str = ""
    date_discovered: str = ""
    risk_level: str = "UNKNOWN"     # LOW_RISK | MEDIUM_RISK | HIGH_RISK | UNKNOWN
    risk_reasons: list[str] = field(default_factory=list)

    @property
    def title(self) -> str:
        """Alias for `role` — prevents AttributeError when code uses job.title."""
        return self.role



@dataclass
class JobMatchScore:
    job_id: str = ""
    overall_score: float = 0.0
    skills_score: float = 0.0
    experience_score: float = 0.0
    education_score: float = 0.0
    role_score: float = 0.0
    location_score: float = 0.0
    preference_score: float = 0.0
    matched_skills: list[str] = field(default_factory=list)
    missing_skills: list[str] = field(default_factory=list)
    concerns: list[str] = field(default_factory=list)


# ── Application ───────────────────────────────────────────────────────────────

# Valid state transitions (enforced in ApplicationRepository)
VALID_TRANSITIONS: dict[str, list[str]] = {
    "DISCOVERED":          ["ANALYZED"],
    "ANALYZED":            ["SHORTLISTED", "DISCOVERED"],
    "SHORTLISTED":         ["USER_APPROVED", "ANALYZED"],
    "USER_APPROVED":       ["IN_PROGRESS"],
    "IN_PROGRESS":         ["READY_FOR_REVIEW", "USER_APPROVED"],
    "READY_FOR_REVIEW":    ["SUBMISSION_APPROVED", "IN_PROGRESS"],
    "SUBMISSION_APPROVED": ["SUBMITTED"],
    "SUBMITTED":           ["INTERVIEW", "REJECTED", "WITHDRAWN"],
    "INTERVIEW":           ["SUBMITTED", "WITHDRAWN"],
    "REJECTED":            [],
    "WITHDRAWN":           [],
}


@dataclass
class Application:
    id: str = ""
    company: str = ""
    role: str = ""
    application_url: str = ""
    source: str = ""
    match_score: float = 0.0
    status: str = "DISCOVERED"
    date_discovered: str = ""
    date_started: str = ""
    date_applied: str = ""
    cv_filename: str = ""
    cv_hash: str = ""
    cover_letter: str = ""
    answers: str = ""           # JSON string
    notes: str = ""
    last_updated: str = ""


# ── Interview ─────────────────────────────────────────────────────────────────

@dataclass
class InterviewRecord:
    id: str = ""
    application_id: str = ""
    company: str = ""
    role: str = ""
    interview_date: str = ""
    interview_time: str = ""
    round: str = ""
    interviewer: str = ""
    meeting_url: str = ""
    status: str = "SCHEDULED"   # SCHEDULED | COMPLETED | CANCELLED
    notes: str = ""


# ── API Usage ─────────────────────────────────────────────────────────────────

@dataclass
class ApiUsageRecord:
    id: Optional[int] = None
    timestamp: str = ""
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    agent: str = ""
    action: str = ""
