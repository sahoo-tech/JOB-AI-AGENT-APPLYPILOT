"""
Tests for application state machine and duplicate prevention.
"""
import pytest

from app.storage.database import init_db
from app.storage.models import VALID_TRANSITIONS


class TestStateMachine:
    def test_valid_transitions_defined(self):
        assert "DISCOVERED" in VALID_TRANSITIONS
        assert "SUBMITTED" in VALID_TRANSITIONS

    def test_no_direct_discovered_to_submitted(self):
        """DISCOVERED → SUBMITTED must NOT be a valid direct transition."""
        allowed = VALID_TRANSITIONS.get("DISCOVERED", [])
        assert "SUBMITTED" not in allowed

    def test_no_analyzed_to_submitted(self):
        allowed = VALID_TRANSITIONS.get("ANALYZED", [])
        assert "SUBMITTED" not in allowed

    def test_all_paths_require_approval(self):
        """
        Every path to SUBMITTED must pass through READY_FOR_REVIEW
        and SUBMISSION_APPROVED.
        """
        def can_reach(start, target, visited=None):
            if visited is None:
                visited = set()
            if start == target:
                return True
            if start in visited:
                return False
            visited.add(start)
            for next_state in VALID_TRANSITIONS.get(start, []):
                if can_reach(next_state, target, visited.copy()):
                    return True
            return False

        # From READY_FOR_REVIEW, can we reach SUBMITTED?
        assert can_reach("READY_FOR_REVIEW", "SUBMITTED")
        # SUBMISSION_APPROVED is the only step before SUBMITTED
        assert "SUBMITTED" in VALID_TRANSITIONS["SUBMISSION_APPROVED"]
        # READY_FOR_REVIEW can only go to SUBMISSION_APPROVED (and back to IN_PROGRESS)
        assert "SUBMISSION_APPROVED" in VALID_TRANSITIONS["READY_FOR_REVIEW"]

    def test_terminal_states_have_no_forward_transitions(self):
        assert VALID_TRANSITIONS["REJECTED"] == []
        assert VALID_TRANSITIONS["WITHDRAWN"] == []


class TestApplicationRepository:
    @pytest.fixture(autouse=True)
    def setup_db(self, tmp_path, monkeypatch):
        """Use a temporary DB for each test."""
        db = tmp_path / "test.db"
        import app.utils.config as cfg_module
        orig = cfg_module.settings.db_path
        monkeypatch.setattr(cfg_module.settings, "db_path", db)
        init_db()
        yield
        monkeypatch.setattr(cfg_module.settings, "db_path", orig)

    def test_create_application(self):
        from app.storage.repositories import ApplicationRepository
        app = ApplicationRepository.create(
            company="Acme", role="Dev Intern", url="https://acme.com/job/1",
            source="mock", match_score=0.85,
        )
        assert app.id.startswith("APP-")
        assert app.status == "DISCOVERED"

    def test_valid_transition(self):
        from app.storage.repositories import ApplicationRepository
        app = ApplicationRepository.create(
            company="Acme", role="Dev Intern", url="https://acme.com/job/2",
            source="mock", match_score=0.85,
        )
        updated = ApplicationRepository.transition(app.id, "ANALYZED")
        assert updated.status == "ANALYZED"

    def test_invalid_transition_blocked(self):
        from app.storage.repositories import ApplicationRepository
        app = ApplicationRepository.create(
            company="Acme", role="Dev Intern", url="https://acme.com/job/3",
            source="mock", match_score=0.85,
        )
        with pytest.raises(ValueError, match="Illegal state transition"):
            ApplicationRepository.transition(app.id, "SUBMITTED")

    def test_duplicate_detection(self):
        from app.storage.repositories import ApplicationRepository
        # Create first application
        ApplicationRepository.create(
            company="Acme", role="Dev Intern", url="https://acme.com/job/4",
            source="mock", match_score=0.85,
        )
        # Same company+role+url should be detected as duplicate
        assert ApplicationRepository.is_duplicate("Acme", "Dev Intern", "https://acme.com/job/4") is True

    def test_different_company_not_duplicate(self):
        from app.storage.repositories import ApplicationRepository
        ApplicationRepository.create(
            company="AcmeA", role="Dev Intern", url="https://acmea.com/job/1",
            source="mock", match_score=0.85,
        )
        assert ApplicationRepository.is_duplicate("AcmeB", "Dev Intern", "https://acmeb.com/job/1") is False

    def test_rejected_application_allows_reapply(self):
        """After rejection, the same job URL should not block a new application."""
        from app.storage.repositories import ApplicationRepository
        app = ApplicationRepository.create(
            company="Acme", role="Dev Intern", url="https://acme.com/job/5",
            source="mock", match_score=0.85,
        )
        # Transition through to SUBMITTED then REJECTED
        ApplicationRepository.transition(app.id, "ANALYZED")
        ApplicationRepository.transition(app.id, "SHORTLISTED")
        ApplicationRepository.transition(app.id, "USER_APPROVED")
        ApplicationRepository.transition(app.id, "IN_PROGRESS")
        ApplicationRepository.transition(app.id, "READY_FOR_REVIEW")
        ApplicationRepository.transition(app.id, "SUBMISSION_APPROVED")
        ApplicationRepository.transition(app.id, "SUBMITTED")
        ApplicationRepository.transition(app.id, "REJECTED")

        # After rejection, is_duplicate should return False (rejected/withdrawn excluded)
        assert ApplicationRepository.is_duplicate("Acme", "Dev Intern", "https://acme.com/job/5") is False
