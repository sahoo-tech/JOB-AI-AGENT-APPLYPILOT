"""
ApplyPilot — Job Search Agent.

Responsible for:
  - Finding jobs from configured providers
  - Collecting and normalising job information
  - Deduplicating jobs
  - Applying deterministic filters
  - Presenting a shortlist to the user
"""
from google.adk.agents import Agent
from google.adk.models import Gemini

from app.tools.job_search import search_jobs, get_job_details
from app.utils.config import settings

_INSTRUCTION = """
You are the ApplyPilot Job Search Agent. Your responsibility is to find relevant
jobs and present a prioritised shortlist to the user.

Core rules:
1. Always deduplicate and filter jobs before presenting them.
2. Never present more jobs to Gemini analysis than necessary (use deterministic
   filters first to reduce the set).
3. Never invent job information — use only data from job providers.
4. Present jobs sorted by match score (highest first).
5. Clearly show risk level for each job.
6. Respect platform rate limits and access policies.

When the user says:
  "find jobs for <role>" → call search_jobs (uses live API by default)
  "search for <query> in <location>" → call search_jobs with location
  "search Internshala for <query>" → call search_jobs with provider='playwright'
  "tell me more about job <id>" → call get_job_details

Available providers: 'api' (Remotive + Arbeitnow aggregated, default), 'playwright' (Internshala live scrape), 'mock' (test data only).
After showing results, ask the user which job they'd like to prepare an application for.
"""

job_search_agent = Agent(
    name="job_search_agent",
    model=Gemini(model=settings.gemini_model),
    instruction=_INSTRUCTION,
    tools=[search_jobs, get_job_details],
    description="Discovers, deduplicates, filters, and ranks jobs matching the candidate profile.",
)
