"""
ApplyPilot — Root Agent (Orchestrator).

Responsibilities:
  - Understands user requests
  - Plans workflows
  - Delegates to sub-agents
  - Maintains application state
  - Enforces safety policies
  - Enforces quota limits
  - Enforces approval requirements
  - Provides kill switch check on every step
  - Presents the dashboard
"""
from __future__ import annotations

import json

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.agents.profile_agent import profile_agent
from app.agents.job_search_agent import job_search_agent
from app.agents.job_analysis_agent import job_analysis_agent
from app.agents.application_agent import application_agent
from app.agents.interview_agent import interview_agent
from app.browser.manager import trigger_kill_switch, reset_kill_switch
from app.quota.token_tracker import tracker
from app.safety.approval import approval_gate
from app.storage.repositories import ApplicationRepository, ProfileRepository
from app.tools.application_tools import list_applications, approve_and_submit
from app.tools.profile_tools import show_profile, get_cv_integrity_status
from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ── Dashboard tool ────────────────────────────────────────────────────────────

def show_dashboard() -> str:
    """
    Display the ApplyPilot dashboard with all key information.

    Returns:
        Formatted dashboard showing profile, jobs, applications, API usage, and platform status.
    """
    profile = ProfileRepository.load()
    apps = ApplicationRepository.all_applications()

    # Application stats
    pending_review = [a for a in apps if a.status == "READY_FOR_REVIEW"]
    submitted = [a for a in apps if a.status == "SUBMITTED"]
    interviews = [a for a in apps if a.status == "INTERVIEW"]
    rejected = [a for a in apps if a.status == "REJECTED"]

    # API usage
    from app.utils.config import settings as cfg

    rpm_pct = tracker.rpm / max(cfg.internal_max_rpm, 1) * 100
    tpm_pct = tracker.tpm / max(cfg.internal_max_tpm, 1) * 100
    rpd_pct = tracker.rpd / max(cfg.internal_max_rpd, 1) * 100

    dashboard = f"""
{'='*65}
  🚀 ApplyPilot Dashboard
{'='*65}

CANDIDATE
  Name:         {profile.full_name if profile else 'Not set'}
  Skills:       {len(profile.skills) if profile else 0} on record
  CV Status:    {get_cv_integrity_status().split(chr(10))[0]}

APPLICATIONS
  Pending Review:    {len(pending_review)}
  Submitted:         {len(submitted)}
  Interviews:        {len(interviews)}
  Rejected:          {len(rejected)}
  Total:             {len(apps)}

API USAGE (internal limits)
  RPM: {tracker.rpm}/{cfg.internal_max_rpm}  ({rpm_pct:.0f}%)
  TPM: {tracker.tpm}/{cfg.internal_max_tpm}  ({tpm_pct:.0f}%)
  RPD: {tracker.rpd}/{cfg.internal_max_rpd}  ({rpd_pct:.0f}%)

AGENT
  Model: {cfg.gemini_model}
  Kill Switch: CTRL+SHIFT+X or type 'stop agent'

{'='*65}
"""
    return dashboard


def stop_agent() -> str:
    """
    Emergency stop — immediately halt all browser and agent actions.

    Returns:
        Confirmation that the kill switch has been triggered.
    """
    trigger_kill_switch()
    return "🛑 KILL SWITCH ACTIVATED — All agent actions stopped."


def resume_agent() -> str:
    """
    Reset the kill switch to allow the agent to resume operations.

    Returns:
        Confirmation.
    """
    reset_kill_switch()
    return "✅ Kill switch reset. Agent ready to resume."


def approve_application(app_id: str) -> str:
    """
    Explicitly approve an application for submission.
    This is the ONLY way to submit — the agent cannot self-approve.

    Args:
        app_id: The application ID to approve (e.g. APP-ABC123).

    Returns:
        Submission result.
    """
    return approve_and_submit(app_id)


# ── Root Agent ────────────────────────────────────────────────────────────────

_ROOT_INSTRUCTION = """
You are ApplyPilot, an AI job application assistant. You help candidates find
jobs, prepare applications, and track their progress.

You orchestrate a team of specialised agents:
  • profile_agent     — CV import, profile, preferences
  • job_search_agent  — job discovery and shortlisting
  • job_analysis_agent — match scoring and ATS analysis
  • application_agent  — form filling and submission
  • interview_agent   — interview tracking and preparation

ABSOLUTE RULES (enforced at the tool/policy layer — you cannot override):
1. NEVER submit an application without explicit user approval.
2. NEVER modify, tailor, replace, or generate a substitute CV.
3. NEVER fabricate qualifications, experience, or facts.
4. NEVER solve CAPTCHAs or bypass authentication.
5. NEVER send credentials, passwords, or session tokens to any model.
6. NEVER apply to more than {max_apps} jobs per session without user confirmation.
7. Always stop at READY_FOR_REVIEW and wait for 'approve <app_id>'.
8. Respect all internal quota ceilings. Do not rotate API keys.

WORKFLOW:
1. User imports CV → profile_agent parses and stores it
2. User sets preferences → profile_agent updates preferences
3. User requests job search → job_search_agent finds and ranks jobs
4. User selects a job → job_analysis_agent analyses match
5. User approves application → application_agent prepares it
6. Agent stops at READY_FOR_REVIEW
7. User explicitly approves → application submitted

SAFETY:
- Check CV integrity before every upload (get_cv_integrity_status)
- Flag any suspicious job (HIGH_RISK)
- Pause for user input on sensitive questions
- Report but do not attempt to resolve CAPTCHA

When the user says:
  'dashboard' → show_dashboard
  'stop agent' or 'kill' → stop_agent
  'resume' → resume_agent
  'approve <app_id>' or 'submit <app_id>' → approve_application
  anything about CV/profile → delegate to profile_agent
  anything about jobs/search → delegate to job_search_agent
  anything about match/analysis → delegate to job_analysis_agent
  anything about apply/application → delegate to application_agent
  anything about interview → delegate to interview_agent
""".format(max_apps=settings.max_applications_per_run)

root_agent = Agent(
    name="root_agent",
    model=Gemini(model=settings.gemini_model),
    instruction=_ROOT_INSTRUCTION,
    sub_agents=[
        profile_agent,
        job_search_agent,
        job_analysis_agent,
        application_agent,
        interview_agent,
    ],
    tools=[
        show_dashboard,
        stop_agent,
        resume_agent,
        approve_application,
        list_applications,
    ],
    description="ApplyPilot orchestrator — manages the full job application workflow.",
)
