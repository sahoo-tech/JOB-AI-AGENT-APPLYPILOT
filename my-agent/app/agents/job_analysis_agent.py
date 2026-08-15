"""
ApplyPilot — Job Analysis Agent.

Responsible for:
  - Extracting requirements from job descriptions
  - Comparing jobs against the candidate profile
  - Calculating match scores (deterministic weights)
  - Identifying strengths, missing requirements, and risks
  - ATS analysis
"""
from __future__ import annotations

import json

from google.adk.agents import Agent
from google.adk.models import Gemini

from app.storage.repositories import JobRepository, ProfileRepository
from app.tools.job_search import score_job
from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def analyze_job_match(job_id: str) -> str:
    """
    Analyse how well the candidate matches a specific job.
    Returns detailed ATS analysis and match score breakdown.

    Args:
        job_id: Job ID to analyse.

    Returns:
        Detailed match analysis report.
    """
    job = JobRepository.get(job_id)
    if not job:
        return f"Job {job_id} not found."

    profile = ProfileRepository.load()
    if not profile:
        return "No candidate profile found. Please import your CV first."

    score = score_job(job, profile)

    report_lines = [
        f"JOB MATCH ANALYSIS",
        f"{'='*50}",
        f"Company:  {job.company}",
        f"Role:     {job.role}",
        f"",
        f"OVERALL MATCH: {score.overall_score * 100:.0f}%",
        f"",
        f"Breakdown:",
        f"  Skills:      {score.skills_score * 100:.0f}%  (weight: 35%)",
        f"  Experience:  {score.experience_score * 100:.0f}%  (weight: 20%)",
        f"  Education:   {score.education_score * 100:.0f}%  (weight: 10%)",
        f"  Role:        {score.role_score * 100:.0f}%  (weight: 15%)",
        f"  Location:    {score.location_score * 100:.0f}%  (weight: 10%)",
        f"  Preferences: {score.preference_score * 100:.0f}%  (weight: 10%)",
        f"",
        f"✅ Matched Skills ({len(score.matched_skills)}):",
        f"   {', '.join(score.matched_skills) or 'None'}",
        f"",
        f"⚠️  Missing Skills ({len(score.missing_skills)}):",
        f"   {', '.join(score.missing_skills) or 'None'}",
        f"",
        f"Risk Level: {job.risk_level}",
    ]

    if score.concerns:
        report_lines.append(f"\nConcerns:")
        for c in score.concerns:
            report_lines.append(f"  • {c}")

    # ATS recommendations
    report_lines.extend([
        f"",
        f"ATS ANALYSIS",
        f"{'='*50}",
        f"Keyword coverage: {len(score.matched_skills)}/{len(job.required_skills + job.preferred_skills)} job keywords found in profile",
        f"",
        f"Recommendations (READ ONLY — these are suggestions, NOT changes to your CV):",
    ])
    if score.missing_skills:
        report_lines.append(f"  • Consider highlighting any experience with: {', '.join(score.missing_skills[:5])}")
    if score.overall_score < 0.5:
        report_lines.append(f"  • Match score is below 50%. Consider applying only if other factors are strong.")

    return "\n".join(report_lines)


def get_ats_analysis(job_id: str) -> str:
    """
    Perform full ATS (Applicant Tracking System) analysis of your CV vs the job.
    Does NOT modify the CV — analysis only.

    Args:
        job_id: Job ID to analyse CV against.

    Returns:
        ATS analysis report with keyword coverage and recommendations.
    """
    return analyze_job_match(job_id)


_INSTRUCTION = """
You are the ApplyPilot Job Analysis Agent. Your responsibility is to provide
accurate, honest analysis of how well the candidate matches each job.

Core rules:
1. The match score is calculated DETERMINISTICALLY by the scoring tool.
   You EXPLAIN the score — you do NOT change the numerical calculation.
2. NEVER overstate the candidate's qualifications.
3. NEVER downplay genuine concerns (missing skills, experience gaps).
4. ATS recommendations are for the user to consider — you NEVER modify the CV.
5. Clearly flag HIGH_RISK jobs.

When the user asks about a job match → call analyze_job_match or get_ats_analysis.
"""

job_analysis_agent = Agent(
    name="job_analysis_agent",
    model=Gemini(model=settings.gemini_model),
    instruction=_INSTRUCTION,
    tools=[analyze_job_match, get_ats_analysis],
    description="Analyses job-candidate match scores, ATS compatibility, and risks.",
)
