"""
ApplyPilot — Job description parser.

Normalises raw job data from any provider into the Job model.
Uses Gemini for skill / requirement extraction (quota-aware).
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Optional

from app.storage.models import Job
from app.utils.logging import get_logger

logger = get_logger(__name__)

_JOB_PARSE_PROMPT = """
You are a precise job description parser. Extract structured data from the job posting below.
Return ONLY valid JSON. Use "" or [] for unknown fields. NEVER invent information.

Schema:
{{
  "role": "",
  "company": "",
  "location": "",
  "remote_status": "",     // "remote" | "hybrid" | "on-site" | "UNKNOWN"
  "salary": "",
  "employment_type": "",   // "full-time" | "part-time" | "internship" | "contract" | "UNKNOWN"
  "experience_required": "",
  "education_required": "",
  "required_skills": [],
  "preferred_skills": [],
  "deadline": ""
}}

JOB POSTING:
{job_text}

Respond with ONLY the JSON object.
"""

_RISK_PROMPT = """
Evaluate this job posting for potential fraud or scam indicators.
Return ONLY valid JSON:
{{
  "risk_level": "LOW_RISK" | "MEDIUM_RISK" | "HIGH_RISK" | "UNKNOWN",
  "reasons": []
}}

Indicators of HIGH_RISK:
- Payment requests, asks for money
- Only Telegram/WhatsApp contact
- Missing company information
- Unrealistic salary
- Requests for credentials or SSN upfront
- Suspicious application instructions

Job posting:
{job_text}

Respond with ONLY the JSON object.
"""


def _call_gemini(prompt: str, agent: str = "job_parser") -> str:
    from google import genai
    from google.genai import types as gtypes
    from app.quota.limiter import limiter
    from app.utils.config import settings

    client = genai.Client(api_key=settings.gemini_api_key)

    def _call():
        return client.models.generate_content(
            model=settings.gemini_model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(temperature=0.0, max_output_tokens=2048),
        )

    resp = limiter.with_retry(_call, agent=agent, action="parse_job")
    text = resp.text.strip()
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]
    return text


def _description_hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:32]


def parse_job(
    *,
    raw_description: str,
    application_url: str,
    source: str,
    company: str = "",
    role: str = "",
    job_id: Optional[str] = None,
    use_llm: bool = True,
) -> Job:
    """
    Parse a raw job posting into a normalised Job model.
    If use_llm=False, only fills fields provided directly (for quota conservation).
    """
    now = datetime.now(timezone.utc).isoformat()
    desc_hash = _description_hash(raw_description)

    if not job_id:
        import uuid
        job_id = f"JOB-{uuid.uuid4().hex[:8].upper()}"

    job = Job(
        job_id=job_id,
        company=company,
        role=role,
        application_url=application_url,
        source=source,
        description=raw_description,
        description_hash=desc_hash,
        date_discovered=now,
    )

    if not use_llm:
        return job

    # LLM extraction
    try:
        parsed = json.loads(_call_gemini(_JOB_PARSE_PROMPT.format(job_text=raw_description[:8000])))
        job.role = parsed.get("role", "") or role
        job.company = parsed.get("company", "") or company
        job.location = parsed.get("location", "UNKNOWN")
        job.remote_status = parsed.get("remote_status", "UNKNOWN")
        job.salary = parsed.get("salary", "UNKNOWN")
        job.employment_type = parsed.get("employment_type", "UNKNOWN")
        job.experience_required = parsed.get("experience_required", "UNKNOWN")
        job.education_required = parsed.get("education_required", "UNKNOWN")
        job.required_skills = parsed.get("required_skills", [])
        job.preferred_skills = parsed.get("preferred_skills", [])
        job.deadline = parsed.get("deadline", "UNKNOWN")
    except Exception as exc:
        logger.warning("Job LLM parsing failed: %s", exc)

    # Risk assessment
    try:
        risk = json.loads(_call_gemini(_RISK_PROMPT.format(job_text=raw_description[:4000])))
        job.risk_level = risk.get("risk_level", "UNKNOWN")
        job.risk_reasons = risk.get("reasons", [])
    except Exception as exc:
        logger.warning("Risk assessment failed: %s", exc)

    return job
