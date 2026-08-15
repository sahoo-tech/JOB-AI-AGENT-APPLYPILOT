"""
Tests for job scoring, deduplication, and filtering.
"""
import pytest

from app.storage.models import Job, CandidateProfile
from app.tools.job_search import score_job, _dedup_jobs, filter_jobs


def _make_profile(skills=None, preferred_roles=None, preferred_locations=None,
                  remote_preference="any", employment_preferences=None):
    p = CandidateProfile()
    p.skills = skills or ["Python", "FastAPI", "PostgreSQL"]
    p.preferred_roles = preferred_roles or ["Backend Intern"]
    p.preferred_locations = preferred_locations or ["Bangalore"]
    p.remote_preference = remote_preference
    p.employment_preferences = employment_preferences or ["internship"]
    p.experience = []
    p.internships = []
    p.education = []
    return p


def _make_job(job_id="J1", required_skills=None, role="Backend Intern",
              location="Bangalore, India", employment_type="internship",
              remote_status="hybrid", risk_level="LOW_RISK"):
    j = Job()
    j.job_id = job_id
    j.company = "TestCo"
    j.role = role
    j.location = location
    j.employment_type = employment_type
    j.remote_status = remote_status
    j.required_skills = required_skills or ["Python", "FastAPI"]
    j.preferred_skills = ["Docker"]
    j.experience_required = "0 years"
    j.education_required = "B.Tech"
    j.risk_level = risk_level
    j.risk_reasons = []
    j.description_hash = f"hash_{job_id}"
    return j


class TestJobScoring:
    def test_perfect_skill_match(self):
        profile = _make_profile(skills=["Python", "FastAPI", "Docker"])
        job = _make_job(required_skills=["Python", "FastAPI"], )
        job.preferred_skills = ["Docker"]
        score = score_job(job, profile)
        assert score.skills_score == 1.0
        assert 0.0 <= score.overall_score <= 1.0

    def test_no_skill_match(self):
        profile = _make_profile(skills=["Java", "Spring"])
        job = _make_job(required_skills=["Python", "FastAPI"])
        score = score_job(job, profile)
        assert score.skills_score == 0.0
        assert "Python" in score.missing_skills or "FastAPI" in score.missing_skills

    def test_score_range(self):
        profile = _make_profile()
        job = _make_job()
        score = score_job(job, profile)
        assert 0.0 <= score.overall_score <= 1.0

    def test_weights_sum_to_one(self):
        from app.tools.job_search import _WEIGHTS
        total = sum(_WEIGHTS.values())
        assert abs(total - 1.0) < 1e-9

    def test_high_risk_in_concerns(self):
        profile = _make_profile()
        job = _make_job(risk_level="HIGH_RISK")
        job.risk_reasons = ["Payment requested"]
        score = score_job(job, profile)
        assert any("HIGH_RISK" in c for c in score.concerns)

    def test_matched_skills_populated(self):
        profile = _make_profile(skills=["Python", "FastAPI", "SQL"])
        job = _make_job(required_skills=["Python", "FastAPI"])
        score = score_job(job, profile)
        assert "python" in score.matched_skills or "Python" in score.matched_skills


class TestDeduplication:
    def test_dedup_by_hash(self):
        j1 = _make_job("J1")
        j2 = _make_job("J2")
        j2.description_hash = j1.description_hash  # same description
        result = _dedup_jobs([j1, j2])
        assert len(result) == 1

    def test_dedup_by_company_role_location(self):
        j1 = _make_job("J1")
        j2 = _make_job("J2")
        j2.description_hash = "different_hash"
        j2.company = j1.company
        j2.role = j1.role
        j2.location = j1.location
        result = _dedup_jobs([j1, j2])
        assert len(result) == 1

    def test_different_jobs_preserved(self):
        j1 = _make_job("J1", role="Backend Intern")
        j2 = _make_job("J2", role="Frontend Intern")
        result = _dedup_jobs([j1, j2])
        assert len(result) == 2

    def test_empty_list(self):
        assert _dedup_jobs([]) == []


class TestFiltering:
    def test_employment_type_filter(self):
        profile = _make_profile(employment_preferences=["internship"])
        j_intern = _make_job("J1", employment_type="internship")
        j_fulltime = _make_job("J2", employment_type="full-time")
        result = filter_jobs([j_intern, j_fulltime], profile)
        ids = [j.job_id for j in result]
        assert "J1" in ids
        assert "J2" not in ids

    def test_high_risk_exclusion(self):
        profile = _make_profile()
        j_ok = _make_job("J1", risk_level="LOW_RISK")
        j_bad = _make_job("J2", risk_level="HIGH_RISK")
        result = filter_jobs([j_ok, j_bad], profile, exclude_high_risk=True)
        assert len(result) == 1
        assert result[0].job_id == "J1"

    def test_unknown_employment_type_passes(self):
        """Jobs with UNKNOWN employment type should not be filtered out."""
        profile = _make_profile(employment_preferences=["internship"])
        j = _make_job("J1", employment_type="UNKNOWN")
        result = filter_jobs([j], profile)
        assert len(result) == 1
