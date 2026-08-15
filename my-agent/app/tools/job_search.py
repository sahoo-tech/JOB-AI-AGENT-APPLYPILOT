"""
ApplyPilot — Job search tools (ADK tool functions).

Provides a pluggable JobProvider abstraction.
Ships with:
  - MockJobProvider  — deterministic test data (no API calls)
  - WebJobProvider   — Playwright-based stub (extend per platform)

Pipeline: search → normalise → deduplicate → filter → return top N
"""
from __future__ import annotations

import hashlib
import json
import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Optional

from app.storage.models import Job, JobMatchScore, CandidateProfile
from app.storage.repositories import JobRepository
from app.parsing.job_parser import parse_job
from app.utils.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ── Provider Abstraction ──────────────────────────────────────────────────────

class JobProvider(ABC):
    @abstractmethod
    def search(self, query: str, location: str = "", limit: int = 50) -> list[dict]:
        """Return a list of raw job dicts."""
        ...

    @abstractmethod
    def get_job_details(self, job_id: str) -> Optional[dict]:
        """Return detailed raw job dict or None."""
        ...


class MockJobProvider(JobProvider):
    """Deterministic mock data for testing and development."""

    _MOCK_JOBS = [
        {
            "id": "MOCK-001",
            "company": "TechCorp India",
            "role": "Backend Engineer Intern",
            "location": "Bangalore, India",
            "remote_status": "hybrid",
            "salary": "₹20,000/month",
            "employment_type": "internship",
            "experience_required": "0-1 years",
            "education_required": "B.Tech/B.E. in CS or related",
            "required_skills": ["Python", "FastAPI", "PostgreSQL", "Git"],
            "preferred_skills": ["Docker", "Redis", "AWS"],
            "application_url": "https://techcorp.example.com/jobs/be-intern",
            "description": "We are looking for a talented Backend Engineer Intern...",
        },
        {
            "id": "MOCK-002",
            "company": "StartupXYZ",
            "role": "Full Stack Developer Intern",
            "location": "Mumbai, India",
            "remote_status": "remote",
            "salary": "₹15,000/month",
            "employment_type": "internship",
            "experience_required": "0 years",
            "education_required": "Any degree",
            "required_skills": ["JavaScript", "React", "Node.js"],
            "preferred_skills": ["TypeScript", "MongoDB"],
            "application_url": "https://startupxyz.example.com/jobs/fullstack",
            "description": "Join our growing team as a Full Stack Developer Intern...",
        },
        {
            "id": "MOCK-003",
            "company": "DataSystems Ltd",
            "role": "Data Science Intern",
            "location": "Hyderabad, India",
            "remote_status": "on-site",
            "salary": "₹25,000/month",
            "employment_type": "internship",
            "experience_required": "0-1 years",
            "education_required": "B.Tech in CS/Statistics",
            "required_skills": ["Python", "Pandas", "Scikit-learn", "SQL"],
            "preferred_skills": ["TensorFlow", "Tableau"],
            "application_url": "https://datasystems.example.com/jobs/ds-intern",
            "description": "Looking for a Data Science Intern with strong Python skills...",
        },
    ]

    def search(self, query: str, location: str = "", limit: int = 50) -> list[dict]:
        query_lower = query.lower()
        results = []
        for job in self._MOCK_JOBS:
            if (
                query_lower in job["role"].lower()
                or query_lower in job["description"].lower()
                or any(query_lower in s.lower() for s in job["required_skills"])
            ):
                if not location or location.lower() in job["location"].lower():
                    results.append(job)
        return results[:limit]

    def get_job_details(self, job_id: str) -> Optional[dict]:
        for job in self._MOCK_JOBS:
            if job["id"] == job_id:
                return job
        return None


class RemotiveJobProvider(JobProvider):
    """Free public Remotive API — remote tech jobs, no API key required."""

    BASE_URL = "https://remotive.com/api/remote-jobs"

    def search(self, query: str, location: str = "", limit: int = 50) -> list[dict]:
        try:
            import httpx
            params = {"search": query, "limit": limit}
            resp = httpx.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            jobs = resp.json().get("jobs", [])
            results = []
            for j in jobs:
                desc = j.get("description", "")
                # Strip HTML tags from description
                import re
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
                results.append({
                    "id": f"REMOTIVE-{j['id']}",
                    "company": j.get("company_name", ""),
                    "role": j.get("title", ""),
                    "location": j.get("candidate_required_location", "Remote"),
                    "remote_status": "remote",
                    "salary": j.get("salary", "UNKNOWN"),
                    "employment_type": j.get("job_type", "full-time").replace("_", "-"),
                    "experience_required": "",
                    "education_required": "",
                    "required_skills": [t for t in j.get("tags", [])],
                    "preferred_skills": [],
                    "application_url": j.get("url", ""),
                    "description": desc[:3000],
                })
            logger.info("Remotive returned %d jobs for query='%s'", len(results), query)
            return results
        except Exception as exc:
            logger.error("RemotiveJobProvider.search failed: %s", exc)
            return []

    def get_job_details(self, job_id: str) -> Optional[dict]:
        return None  # Remotive doesn't support single-job lookup by ID


class ArbeitnowJobProvider(JobProvider):
    """Free public Arbeitnow API — aggregates LinkedIn, Indeed, Glassdoor listings."""

    BASE_URL = "https://www.arbeitnow.com/api/job-board-api"

    def search(self, query: str, location: str = "", limit: int = 50) -> list[dict]:
        try:
            import httpx
            params: dict = {}
            if query:
                params["search"] = query
            if location:
                params["location"] = location
            resp = httpx.get(self.BASE_URL, params=params, timeout=15)
            resp.raise_for_status()
            jobs = resp.json().get("data", [])[:limit]
            results = []
            for j in jobs:
                desc = j.get("description", "")
                import re
                desc = re.sub(r"<[^>]+>", " ", desc).strip()
                results.append({
                    "id": f"ARBEITNOW-{j.get('slug', j.get('title', ''))[:20]}",
                    "company": j.get("company_name", ""),
                    "role": j.get("title", ""),
                    "location": j.get("location", location or "Remote"),
                    "remote_status": "remote" if j.get("remote") else "on-site",
                    "salary": (lambda s: s[0] if isinstance(s, list) and s else str(s) if s else "UNKNOWN")(j.get("salary")),
                    "employment_type": (lambda jt: jt[0] if isinstance(jt, list) and jt else "full-time")(j.get("job_types")),
                    "experience_required": "",
                    "education_required": "",
                    "required_skills": j.get("tags", []),
                    "preferred_skills": [],
                    "application_url": j.get("url", ""),
                    "description": desc[:3000],
                })
            logger.info("Arbeitnow returned %d jobs for query='%s'", len(results), query)
            return results
        except Exception as exc:
            logger.error("ArbeitnowJobProvider.search failed: %s", exc)
            return []

    def get_job_details(self, job_id: str) -> Optional[dict]:
        return None


class PlaywrightJobProvider(JobProvider):
    """
    Playwright-based live scraper for Internshala (internships/fresher jobs).
    Respects platform ToS — does not bypass authentication or anti-bot systems.
    """

    def search(self, query: str, location: str = "", limit: int = 30) -> list[dict]:
        try:
            from playwright.sync_api import sync_playwright
            import re

            slug = query.lower().replace(" ", "-")
            url = f"https://internshala.com/jobs/keywords-{slug}"
            if location:
                url = f"https://internshala.com/jobs/keywords-{slug}/location-{location.lower().replace(' ', '-')}"

            results = []
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, timeout=30000)
                page.wait_for_timeout(3000)  # let JS render

                cards = page.query_selector_all(".individual_internship")
                for card in cards[:limit]:
                    try:
                        role = card.query_selector(".job-internship-name")
                        company = card.query_selector(".company-name")
                        loc = card.query_selector(".location_link")
                        link = card.query_selector("a.view_detail_button")
                        salary = card.query_selector(".stipend")

                        role_text = role.inner_text().strip() if role else ""
                        company_text = company.inner_text().strip() if company else ""
                        loc_text = loc.inner_text().strip() if loc else location or "India"
                        salary_text = salary.inner_text().strip() if salary else "UNKNOWN"
                        href = link.get_attribute("href") if link else ""
                        full_url = f"https://internshala.com{href}" if href and href.startswith("/") else href or ""

                        results.append({
                            "id": f"INTERNSHALA-{re.sub(chr(32), '-', role_text[:20])}-{company_text[:10]}",
                            "company": company_text,
                            "role": role_text,
                            "location": loc_text,
                            "remote_status": "remote" if "work from home" in loc_text.lower() else "on-site",
                            "salary": salary_text,
                            "employment_type": "internship" if "intern" in role_text.lower() else "full-time",
                            "experience_required": "0 years",
                            "education_required": "",
                            "required_skills": [],
                            "preferred_skills": [],
                            "application_url": full_url,
                            "description": f"{role_text} at {company_text} in {loc_text}. Stipend: {salary_text}.",
                        })
                    except Exception:
                        continue

                browser.close()

            logger.info("PlaywrightJobProvider scraped %d jobs from Internshala", len(results))
            return results
        except Exception as exc:
            logger.error("PlaywrightJobProvider.search failed: %s", exc)
            return []

    def get_job_details(self, job_id: str) -> Optional[dict]:
        return None


# ── Deduplication ─────────────────────────────────────────────────────────────

def _dedup_jobs(jobs: list[Job]) -> list[Job]:
    """Remove obvious duplicates by description hash and normalised company+role+location."""
    seen_hashes: set[str] = set()
    seen_keys: set[str] = set()
    result = []
    for job in jobs:
        key = f"{job.company.lower().strip()}|{job.role.lower().strip()}|{job.location.lower().strip()}"
        if job.description_hash in seen_hashes or key in seen_keys:
            continue
        seen_hashes.add(job.description_hash)
        seen_keys.add(key)
        result.append(job)
    return result


# ── Deterministic scoring ─────────────────────────────────────────────────────

_WEIGHTS = {
    "skills": 0.35,
    "experience": 0.20,
    "education": 0.10,
    "role": 0.15,
    "location": 0.10,
    "preferences": 0.10,
}


def score_job(job: Job, profile: CandidateProfile, weights: Optional[dict] = None) -> JobMatchScore:
    """
    Deterministic scoring of a job against a candidate profile.
    Weights are configurable; LLM explains but cannot change the calculation.
    """
    w = weights or _WEIGHTS
    # Build canonical (original-casing) maps for case-insensitive comparison
    profile_skills_lower = {s.lower().strip() for s in profile.skills}
    job_required_canonical = {s.lower().strip(): s for s in job.required_skills}  # lower → canonical
    job_preferred_canonical = {s.lower().strip(): s for s in job.preferred_skills}
    job_required_lower = set(job_required_canonical.keys())
    job_preferred_lower = set(job_preferred_canonical.keys())

    # Skills score (case-insensitive sets)
    matched_lower = profile_skills_lower & (job_required_lower | job_preferred_lower)
    missing_lower = job_required_lower - profile_skills_lower
    skills_score = len(matched_lower) / max(len(job_required_lower | job_preferred_lower), 1)

    # Restore canonical casing for display
    matched = sorted(
        job_required_canonical.get(s) or job_preferred_canonical.get(s) or s
        for s in matched_lower
    )
    missing = sorted(
        job_required_canonical.get(s, s) for s in missing_lower
    )

    # Experience score (simple heuristic)
    exp_years = sum(1 for e in profile.experience) + sum(0.5 for i in profile.internships)
    req_text = (job.experience_required or "").lower()
    if "0" in req_text or "fresher" in req_text or "entry" in req_text:
        experience_score = 1.0
    elif "1" in req_text or "one" in req_text:
        experience_score = min(exp_years / 1.0, 1.0)
    elif "2" in req_text:
        experience_score = min(exp_years / 2.0, 1.0)
    else:
        experience_score = 0.5

    # Education score
    edu_text = (job.education_required or "").lower()
    has_degree = bool(profile.education)
    education_score = 1.0 if has_degree else (0.5 if "any" in edu_text else 0.2)

    # Role relevance
    role_score = 0.0
    for pref in profile.preferred_roles:
        if pref.lower() in job.role.lower() or job.role.lower() in pref.lower():
            role_score = 1.0
            break
    if role_score == 0.0:
        role_score = 0.4  # generic relevance

    # Location score
    location_score = 0.5
    for loc in profile.preferred_locations:
        if loc.lower() in (job.location or "").lower():
            location_score = 1.0
            break
    remote_pref = profile.remote_preference.lower()
    job_remote = job.remote_status.lower()
    if remote_pref == "remote" and job_remote == "remote":
        location_score = 1.0
    elif remote_pref == "any":
        location_score = max(location_score, 0.8)

    # Preferences score
    preference_score = 0.5
    for emp_pref in profile.employment_preferences:
        if emp_pref.lower() in (job.employment_type or "").lower():
            preference_score = 1.0
            break

    overall = (
        skills_score * w["skills"]
        + experience_score * w["experience"]
        + education_score * w["education"]
        + role_score * w["role"]
        + location_score * w["location"]
        + preference_score * w["preferences"]
    )

    concerns = []
    if job.risk_level in ("HIGH_RISK",):
        concerns.append(f"Risk: {job.risk_level} — {', '.join(job.risk_reasons)}")
    if missing:
        concerns.append(f"Missing skills: {', '.join(list(missing)[:5])}")

    return JobMatchScore(
        job_id=job.job_id,
        overall_score=round(overall, 4),
        skills_score=round(skills_score, 4),
        experience_score=round(experience_score, 4),
        education_score=round(education_score, 4),
        role_score=round(role_score, 4),
        location_score=round(location_score, 4),
        preference_score=round(preference_score, 4),
        matched_skills=matched,
        missing_skills=missing,
        concerns=concerns,
    )


# ── Deterministic filtering ───────────────────────────────────────────────────

def filter_jobs(
    jobs: list[Job],
    profile: CandidateProfile,
    min_score: float = 0.3,
    exclude_high_risk: bool = False,
) -> list[Job]:
    """Apply deterministic filters before LLM analysis."""
    result = []
    for job in jobs:
        if exclude_high_risk and job.risk_level == "HIGH_RISK":
            continue
        # Employment type filter
        if profile.employment_preferences:
            emp_lower = job.employment_type.lower()
            match = any(p.lower() in emp_lower for p in profile.employment_preferences)
            if not match and job.employment_type not in ("UNKNOWN", ""):
                continue
        result.append(job)
    return result


# ── ADK Tool Functions ────────────────────────────────────────────────────────

def search_jobs(
    query: str,
    location: str = "",
    provider: str = "api",
    max_results: int = 10,
) -> str:
    """
    Search for jobs matching the query and location.

    Args:
        query: Job title, skill, or keyword to search for.
        location: Optional location filter (city, country).
        provider: Job provider to use: 'mock' for testing.
        max_results: Maximum number of jobs to return after filtering.

    Returns:
        JSON string with a list of shortlisted job summaries.
    """
    from app.storage.repositories import ProfileRepository
    profile = ProfileRepository.load()
    if not profile:
        return json.dumps({"error": "No candidate profile found. Please import your CV first."})

    # Choose provider
    if provider == "mock":
        prov = MockJobProvider()
    elif provider == "remotive":
        prov = RemotiveJobProvider()
    elif provider == "arbeitnow":
        prov = ArbeitnowJobProvider()
    elif provider == "playwright":
        prov = PlaywrightJobProvider()
    elif provider == "api":
        # Aggregate from both free APIs
        raw_remotive = RemotiveJobProvider().search(query, location, limit=max_results * 2)
        raw_arbeitnow = ArbeitnowJobProvider().search(query, location, limit=max_results * 2)
        raw_jobs = raw_remotive + raw_arbeitnow
        prov = None  # already fetched
    else:
        return json.dumps({"error": f"Unknown provider '{provider}'. Use: mock, api, remotive, arbeitnow, playwright."})

    # Search (skip if already fetched via 'api' aggregate)
    if prov is not None:
        raw_jobs = prov.search(query, location)
    logger.info("Provider returned %d raw jobs", len(raw_jobs))

    # Convert to Job models
    jobs: list[Job] = []
    for raw in raw_jobs:
        job = Job(
            job_id=raw.get("id", f"JOB-{uuid.uuid4().hex[:8].upper()}"),
            company=raw.get("company", ""),
            role=raw.get("role", ""),
            location=raw.get("location", "UNKNOWN"),
            remote_status=raw.get("remote_status", "UNKNOWN"),
            salary=raw.get("salary", "UNKNOWN"),
            employment_type=raw.get("employment_type", "UNKNOWN"),
            experience_required=raw.get("experience_required", "UNKNOWN"),
            education_required=raw.get("education_required", "UNKNOWN"),
            required_skills=raw.get("required_skills", []),
            preferred_skills=raw.get("preferred_skills", []),
            application_url=raw.get("application_url", ""),
            source=provider,
            description=raw.get("description", ""),
            description_hash=hashlib.sha256(raw.get("description", "").encode()).hexdigest()[:32],
            date_discovered=datetime.now(timezone.utc).isoformat(),
        )
        jobs.append(job)

    # Deduplicate
    jobs = _dedup_jobs(jobs)
    logger.info("After dedup: %d jobs", len(jobs))

    # Filter
    jobs = filter_jobs(jobs, profile)
    logger.info("After filter: %d jobs", len(jobs))

    # Score
    scored: list[tuple[Job, JobMatchScore]] = []
    for job in jobs:
        s = score_job(job, profile)
        scored.append((job, s))
        JobRepository.upsert(job)
        JobRepository.save_score(s)

    # Sort by score, take top N
    scored.sort(key=lambda x: x[1].overall_score, reverse=True)
    top = scored[:max_results]

    results = []
    for idx, (job, score) in enumerate(top, 1):
        results.append({
            "rank": idx,
            "job_id": job.job_id,
            "company": job.company,
            "role": job.role,
            "location": job.location,
            "remote": job.remote_status,
            "employment_type": job.employment_type,
            "match_score": f"{score.overall_score * 100:.0f}%",
            "matched_skills": score.matched_skills,
            "missing_skills": score.missing_skills,
            "risk": job.risk_level,
            "concerns": score.concerns,
            "application_url": job.application_url,
        })

    summary = (
        f"{len(raw_jobs)} jobs discovered → {len(jobs)} after dedup/filter → "
        f"{len(top)} shortlisted"
    )
    return json.dumps({"summary": summary, "jobs": results}, indent=2)


def get_job_details(job_id: str) -> str:
    """
    Get detailed information about a specific job.

    Args:
        job_id: The job ID returned from search_jobs.

    Returns:
        JSON string with full job details and match score.
    """
    job = JobRepository.get(job_id)
    if not job:
        return json.dumps({"error": f"Job {job_id} not found"})

    result = {
        "job_id": job.job_id,
        "company": job.company,
        "role": job.role,
        "location": job.location,
        "remote_status": job.remote_status,
        "salary": job.salary,
        "employment_type": job.employment_type,
        "experience_required": job.experience_required,
        "education_required": job.education_required,
        "required_skills": job.required_skills,
        "preferred_skills": job.preferred_skills,
        "deadline": job.deadline,
        "application_url": job.application_url,
        "risk_level": job.risk_level,
        "risk_reasons": job.risk_reasons,
        "description": job.description[:500] + "..." if len(job.description) > 500 else job.description,
    }
    return json.dumps(result, indent=2)
