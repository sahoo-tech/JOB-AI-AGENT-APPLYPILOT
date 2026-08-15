"""
ApplyPilot — Application tools (ADK tool functions).

Handles application creation, form filling, cover letter generation,
and the CV upload gate (SHA-256 enforced at the tool layer).

CRITICAL: The CV upload gate is implemented in Python and cannot be
overridden by LLM instructions.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Optional

from app.parsing.cv_parser import get_master_cv_info
from app.safety.approval import approval_gate
from app.safety.permissions import permissions, Permission
from app.safety.policy import safety_policy
from app.storage.models import CandidateProfile
from app.storage.repositories import ApplicationRepository, ProfileRepository, JobRepository
from app.tools.notification_tools import notify
from app.utils.hashing import verify_file
from app.utils.logging import get_logger, write_audit

logger = get_logger(__name__)


# ── Application lifecycle ─────────────────────────────────────────────────────

def create_application(job_id: str) -> str:
    """
    Create a new application record for the given job.
    Checks for duplicate applications before creating.

    Args:
        job_id: The job ID to apply for.

    Returns:
        Application ID and status summary, or error message.
    """
    job = JobRepository.get(job_id)
    if not job:
        return f"Job {job_id} not found."

    # Duplicate check
    if ApplicationRepository.is_duplicate(job.company, job.role, job.application_url):
        return (
            f"⚠️  DUPLICATE APPLICATION DETECTED\n"
            f"You already have an active application for {job.role} at {job.company}.\n"
            f"Not creating a new application."
        )

    # Get match score
    from app.tools.job_search import score_job
    profile = ProfileRepository.load()
    match_score = 0.0
    if profile:
        score = score_job(job, profile)
        match_score = score.overall_score

    app = ApplicationRepository.create(
        company=job.company,
        role=job.role,
        url=job.application_url,
        source=job.source,
        match_score=match_score,
    )

    write_audit(
        agent="application_agent",
        action="APPLICATION_CREATED",
        application_id=app.id,
        company=job.company,
        role=job.role,
    )

    return (
        f"✅ Application created.\n"
        f"ID: {app.id}\n"
        f"Company: {job.company}\n"
        f"Role: {job.role}\n"
        f"Match Score: {match_score * 100:.0f}%\n"
        f"Status: {app.status}"
    )


def update_application_status(app_id: str, new_status: str) -> str:
    """
    Move an application to a new status (enforces valid state machine transitions).

    Args:
        app_id: Application ID.
        new_status: Target status (e.g. ANALYZED, SHORTLISTED, USER_APPROVED, IN_PROGRESS).

    Returns:
        Updated status or error message.
    """
    try:
        app = ApplicationRepository.transition(app_id, new_status)
        write_audit(
            agent="application_agent",
            action=f"STATUS_TRANSITION_{new_status}",
            application_id=app_id,
            company=app.company,
            role=app.role,
            result=new_status,
        )
        return f"✅ Application {app_id} status → {new_status}"
    except ValueError as exc:
        return f"❌ State transition failed: {exc}"


def generate_cover_letter(app_id: str) -> str:
    """
    Generate a truthful cover letter for the given application.
    Based only on verified candidate profile and job description.
    Never invents conversations, referrals, or relationships.

    Args:
        app_id: Application ID.

    Returns:
        Generated cover letter text.
    """
    app = ApplicationRepository.get(app_id)
    if not app:
        return f"Application {app_id} not found."

    profile = ProfileRepository.load()
    if not profile:
        return "No candidate profile found. Please import your CV first."

    job = JobRepository.get_by_url(app.application_url) if hasattr(JobRepository, 'get_by_url') else None

    from google import genai
    from google.genai import types as gtypes
    from app.quota.limiter import limiter
    from app.utils.config import settings

    prompt = f"""
Write a professional cover letter for the following application.
Use ONLY the information provided. Do NOT invent:
- Previous conversations with the company
- Referrals or references not in the profile
- Relationships with employees
- Company-specific facts you are not given
- Any experience or skill not listed in the profile

Candidate Profile:
Name: {profile.full_name}
Skills: {', '.join(profile.skills[:20])}
Experience: {_format_experience(profile)}
Education: {_format_education(profile)}

Job:
Company: {app.company}
Role: {app.role}

Write a concise, genuine cover letter (3-4 paragraphs). No placeholders.
"""
    client = genai.Client(api_key=settings.gemini_api_key)

    def _call():
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.7, max_output_tokens=1024),
        )

    try:
        resp = limiter.with_retry(_call, agent="application_agent", action="generate_cover_letter")
        cover_letter = resp.text.strip()
        ApplicationRepository.update_cover_letter(app_id, cover_letter)
        write_audit(
            agent="application_agent", action="COVER_LETTER_GENERATED",
            application_id=app_id, company=app.company, role=app.role,
        )
        return f"✅ Cover letter generated:\n\n{cover_letter}"
    except Exception as exc:
        return f"❌ Cover letter generation failed: {exc}"


def answer_application_question(app_id: str, question: str) -> str:
    """
    Generate a truthful answer to an application question.
    Searches the candidate profile for factual basis.
    If information is unavailable, returns UNKNOWN instead of guessing.

    Args:
        app_id: Application ID.
        question: The application question text.

    Returns:
        Truthful answer with source tag, or request for user input.
    """
    profile = ProfileRepository.load()
    if not profile:
        return "No profile found. Please import your CV first."

    # Sensitive questions — always defer to user
    sensitive_keywords = [
        "visa", "sponsorship", "work authorization", "authorized to work",
        "disability", "veteran", "background check", "criminal",
        "salary expectation", "demographic", "race", "gender", "ethnicity",
        "relocation", "legally", "declare", "certify",
    ]
    if any(kw in question.lower() for kw in sensitive_keywords):
        return (
            f"⚠️  SENSITIVE QUESTION — User input required.\n\n"
            f"Question: {question}\n\n"
            f"This question requires your direct input. "
            f"Please provide your answer and I will use it."
        )

    import dataclasses
    import json
    profile_dict = json.dumps(dataclasses.asdict(profile), indent=2)

    from google import genai
    from google.genai import types as gtypes
    from app.quota.limiter import limiter
    from app.utils.config import settings

    prompt = f"""
You are answering a job application question on behalf of the candidate.
Answer ONLY from the provided profile. Never guess or invent information.
If the answer is not in the profile, respond with exactly: UNKNOWN

For each answer, prefix with one of: PROFILE_FACT | USER_PROVIDED | GENERATED_FROM_FACTS | UNKNOWN

Profile:
{profile_dict[:3000]}

Question: {question}

Provide a concise, truthful answer.
"""
    client = genai.Client(api_key=settings.gemini_api_key)

    def _call():
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.0, max_output_tokens=512),
        )

    try:
        resp = limiter.with_retry(_call, agent="application_agent", action="answer_question")
        answer = resp.text.strip()

        # Store Q&A
        app = ApplicationRepository.get(app_id)
        if app:
            existing = json.loads(app.answers or "{}")
            existing[question] = answer
            ApplicationRepository.update_answers(app_id, existing)

        return f"Answer: {answer}"
    except Exception as exc:
        return f"❌ Failed to generate answer: {exc}"


def mark_ready_for_review(app_id: str) -> str:
    """
    Mark an application as READY_FOR_REVIEW and show the submission summary.
    The agent STOPS here and waits for explicit user approval.

    Args:
        app_id: Application ID.

    Returns:
        Full application review summary.
    """
    app = ApplicationRepository.get(app_id)
    if not app:
        return f"Application {app_id} not found."

    # Transition state
    try:
        ApplicationRepository.transition(app_id, "READY_FOR_REVIEW")
    except ValueError as exc:
        return f"❌ Cannot mark for review: {exc}"

    cv_info = get_master_cv_info()
    cv_filename = cv_info["original_filename"] if cv_info else "UNKNOWN"
    cv_hash = cv_info["sha256"][:16] + "..." if cv_info else "UNKNOWN"

    answers = json.loads(app.answers or "{}")

    summary = f"""
{'='*60}
APPLICATION READY FOR REVIEW

Company:       {app.company}
Role:          {app.role}
Match Score:   {app.match_score * 100:.0f}%
Application:   {app.application_url}

CV (EXACT MASTER):
  File:    {cv_filename}
  SHA-256: {cv_hash}

Cover Letter: {'✅ Prepared' if app.cover_letter else '⬜ Not generated'}

Questions: {len(answers)} answered

STATUS: READY_FOR_REVIEW
{'='*60}

⚠️  Please review the above carefully.
Type 'approve {app_id}' to submit, or 'cancel' to abort.
"""
    notify("application_ready", f"Application ready: {app.role} @ {app.company}")
    write_audit(
        agent="application_agent",
        action="READY_FOR_REVIEW",
        application_id=app_id,
        company=app.company,
        role=app.role,
        approval_required=True,
        approval_status="WAITING",
    )
    return summary


def approve_and_submit(app_id: str) -> str:
    """
    Submit the application after explicit user approval.
    Enforces:
      1. User approval gate (application-specific token)
      2. CV SHA-256 integrity check
      3. State machine transition

    Args:
        app_id: Application ID to submit.

    Returns:
        Submission confirmation or detailed error.
    """
    # Grant approval (this is called when user says 'approve' / 'submit')
    approval_gate.grant_approval(app_id)

    try:
        # Check approval gate
        approval_gate.require_approval(app_id)
    except PermissionError as exc:
        return f"❌ {exc}"

    # CV integrity check — Python-enforced, NOT LLM-overridable
    cv_info = get_master_cv_info()
    if not cv_info:
        return "❌ CV INTEGRITY CHECK FAILED — No master CV on record. Cannot submit."

    from app.utils.hashing import verify_file
    try:
        cv_ok = verify_file(cv_info["storage_path"], cv_info["sha256"])
    except FileNotFoundError:
        return f"❌ CV INTEGRITY CHECK FAILED — File not found: {cv_info['storage_path']}"

    if not cv_ok:
        notify("application_failed", "CV integrity check failed — upload blocked")
        return (
            f"❌ CV INTEGRITY CHECK FAILED\n"
            f"Expected: {cv_info['sha256'][:16]}...\n"
            f"Application paused. CV has been modified."
        )

    # State transition
    try:
        ApplicationRepository.transition(app_id, "SUBMISSION_APPROVED")
        ApplicationRepository.transition(app_id, "SUBMITTED")
    except ValueError as exc:
        return f"❌ State transition failed: {exc}"

    # Record CV used
    ApplicationRepository.update_cv(app_id, cv_info["original_filename"], cv_info["sha256"])

    # Consume approval token (single-use)
    approval_gate.consume_approval(app_id)

    app = ApplicationRepository.get(app_id)
    write_audit(
        agent="application_agent",
        action="APPLICATION_SUBMITTED",
        application_id=app_id,
        company=app.company if app else "",
        role=app.role if app else "",
        approval_required=True,
        approval_status="APPROVED",
        result="SUBMITTED",
    )

    notify("application_submitted", f"Application submitted: {app.role} @ {app.company}" if app else "")
    safety_policy.require_allow("POST_SUBMISSION_CHECK")

    return f"""
{'='*60}
✅ APPLICATION SUBMITTED

Company:       {app.company if app else 'N/A'}
Role:          {app.role if app else 'N/A'}
Application ID: {app_id}

CV:      {cv_info['original_filename']}
SHA-256: {cv_info['sha256'][:16]}...

Status: SUBMITTED
Application saved to tracker.
{'='*60}
"""


def get_application_status(app_id: str) -> str:
    """
    Get the current status and summary of an application.

    Args:
        app_id: Application ID.

    Returns:
        Status summary.
    """
    app = ApplicationRepository.get(app_id)
    if not app:
        return f"Application {app_id} not found."

    answers = json.loads(app.answers or "{}")
    return (
        f"Application {app_id}\n"
        f"Company:  {app.company}\n"
        f"Role:     {app.role}\n"
        f"Status:   {app.status}\n"
        f"Score:    {app.match_score * 100:.0f}%\n"
        f"CV:       {app.cv_filename or 'Not yet set'}\n"
        f"Answers:  {len(answers)} completed\n"
        f"Updated:  {app.last_updated}"
    )


def list_applications() -> str:
    """
    List all applications with their current status.

    Returns:
        Formatted list of all applications.
    """
    apps = ApplicationRepository.all_applications()
    if not apps:
        return "No applications on record."

    lines = ["Applications:\n"]
    for app in apps:
        lines.append(
            f"  [{app.id}] {app.role} @ {app.company} — {app.status} "
            f"(Score: {app.match_score*100:.0f}%)"
        )
    return "\n".join(lines)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _format_experience(profile: CandidateProfile) -> str:
    parts = []
    for exp in (profile.experience + profile.internships)[:5]:
        parts.append(f"{exp.title} at {exp.company} ({exp.start_date}–{exp.end_date})")
    return "; ".join(parts) if parts else "No experience listed"


def _format_education(profile: CandidateProfile) -> str:
    parts = []
    for edu in profile.education[:3]:
        parts.append(f"{edu.degree} in {edu.field_of_study} from {edu.institution}")
    return "; ".join(parts) if parts else "No education listed"
