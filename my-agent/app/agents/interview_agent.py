"""
ApplyPilot — Interview Agent.

Responsible for:
  - Tracking interview schedules
  - Generating role-specific preparation material
  - Preparing mock interview questions
  - Conducting mock interviews
"""
from __future__ import annotations

import json

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.storage.models import InterviewRecord
from app.storage.repositories import InterviewRepository, ApplicationRepository, ProfileRepository
from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def track_interview(
    application_id: str,
    interview_date: str,
    interview_time: str,
    round: str = "1",
    interviewer: str = "",
    meeting_url: str = "",
    notes: str = "",
) -> str:
    """
    Record an interview for an application.

    Args:
        application_id: The application ID.
        interview_date: Date of the interview (e.g., '2026-09-01').
        interview_time: Time of the interview (e.g., '14:00 IST').
        round: Interview round (e.g., '1', '2', 'HR', 'Technical').
        interviewer: Name of the interviewer (optional).
        meeting_url: Video call URL (optional).
        notes: Additional notes.

    Returns:
        Interview record confirmation.
    """
    app = ApplicationRepository.get(application_id)
    if not app:
        return f"Application {application_id} not found."

    record = InterviewRecord(
        application_id=application_id,
        company=app.company,
        role=app.role,
        interview_date=interview_date,
        interview_time=interview_time,
        round=round,
        interviewer=interviewer,
        meeting_url=meeting_url,
        notes=notes,
        status="SCHEDULED",
    )
    record = InterviewRepository.create(record)

    # Update application status
    try:
        ApplicationRepository.transition(application_id, "INTERVIEW")
    except ValueError:
        pass  # Already in INTERVIEW or beyond

    return (
        f"✅ Interview tracked.\n"
        f"ID: {record.id}\n"
        f"Company: {app.company}\n"
        f"Role: {app.role}\n"
        f"Date: {interview_date} at {interview_time}\n"
        f"Round: {round}\n"
        f"Meeting: {meeting_url or 'Not provided'}"
    )


def prepare_interview(application_id: str) -> str:
    """
    Generate interview preparation material for the given application.
    Based only on verified company info and the user's actual profile.

    Args:
        application_id: Application ID.

    Returns:
        Interview preparation guide.
    """
    app = ApplicationRepository.get(application_id)
    if not app:
        return f"Application {application_id} not found."

    profile = ProfileRepository.load()
    if not profile:
        return "No candidate profile found. Please import your CV first."

    from google import genai
    from google.genai import types as gtypes
    from app.quota.limiter import limiter

    prompt = f"""
Create an interview preparation guide for this candidate and role.
Use ONLY the information provided. Do NOT invent company facts or relationships.

Candidate:
Name: {profile.full_name}
Skills: {', '.join(profile.skills[:20])}
Experience: {'; '.join(f"{e.title} at {e.company}" for e in profile.experience[:5])}
Projects: {'; '.join(p.name for p in profile.projects[:5])}

Target Role:
Company: {app.company}
Position: {app.role}

Generate:
1. 5 likely technical questions for this role
2. 5 behavioral questions (STAR format)
3. Key topics to review based on the candidate's skills
4. 3 projects from the candidate's profile to highlight
5. 3 potential weak areas to prepare for

Keep answers truthful and based on the candidate's actual profile.
"""
    client = genai.Client(api_key=settings.gemini_api_key)

    def _call():
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.7, max_output_tokens=2048),
        )

    try:
        resp = limiter.with_retry(_call, agent="interview_agent", action="prepare_interview")
        return f"📚 INTERVIEW PREPARATION — {app.role} @ {app.company}\n\n{resp.text}"
    except Exception as exc:
        return f"❌ Failed to generate preparation material: {exc}"


def list_interviews() -> str:
    """
    List all upcoming interviews.

    Returns:
        Formatted list of interviews.
    """
    apps = ApplicationRepository.all_applications()
    interview_apps = [a for a in apps if a.status in ("INTERVIEW", "SUBMITTED")]

    if not interview_apps:
        return "No upcoming interviews on record."

    lines = ["Interviews:\n"]
    for app in interview_apps:
        interviews = InterviewRepository.for_application(app.id)
        for iv in interviews:
            lines.append(
                f"  [{iv.id}] {app.role} @ {app.company}\n"
                f"         Date: {iv.interview_date} {iv.interview_time}\n"
                f"         Round: {iv.round} | Status: {iv.status}\n"
                f"         Meeting: {iv.meeting_url or 'Not set'}"
            )
    return "\n".join(lines)


_INSTRUCTION = """
You are the ApplyPilot Interview Agent. Your responsibility is to help the
candidate prepare for and track job interviews.

Core rules:
1. Use ONLY the candidate's actual profile and verified company information.
2. Never invent company-specific anecdotes, connections, or facts.
3. Mock interview questions should be realistic for the role and the candidate's level.
4. Highlight actual projects and skills from the profile.
5. Honestly flag weak areas — don't over-reassure.

When the user says:
  "I have an interview for <app_id>" → call track_interview
  "prepare me for <app_id>" → call prepare_interview
  "show my interviews" → call list_interviews
"""

interview_agent = Agent(
    name="interview_agent",
    model=Gemini(model=settings.gemini_model),
    instruction=_INSTRUCTION,
    tools=[track_interview, prepare_interview, list_interviews],
    description="Tracks interviews and generates truthful preparation material.",
)
