"""
Tests for CV integrity: import, hash verification, mismatch rejection.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

from app.utils.hashing import hash_file, hash_bytes, verify_file


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_temp_file(content: bytes = b"Hello CV content") -> Path:
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    tmp.write(content)
    tmp.close()
    return Path(tmp.name)


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestHashFile:
    def test_hash_file_deterministic(self):
        f = _make_temp_file(b"test content")
        try:
            h1 = hash_file(f)
            h2 = hash_file(f)
            assert h1 == h2
            assert len(h1) == 64  # SHA-256 hex = 64 chars
        finally:
            os.unlink(f)

    def test_hash_bytes(self):
        data = b"sample data"
        h = hash_bytes(data)
        assert len(h) == 64

    def test_hash_different_content(self):
        f1 = _make_temp_file(b"content A")
        f2 = _make_temp_file(b"content B")
        try:
            assert hash_file(f1) != hash_file(f2)
        finally:
            os.unlink(f1)
            os.unlink(f2)

    def test_verify_file_match(self):
        f = _make_temp_file(b"verify me")
        try:
            expected = hash_file(f)
            assert verify_file(f, expected) is True
        finally:
            os.unlink(f)

    def test_verify_file_mismatch_blocks(self):
        """Modified file must fail verification."""
        f = _make_temp_file(b"original content")
        try:
            expected = hash_file(f)
            # Modify the file
            f.write_bytes(b"modified content")
            assert verify_file(f, expected) is False
        finally:
            os.unlink(f)

    def test_verify_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            verify_file("/nonexistent/path/cv.pdf", "abc123")


class TestCVImportSHA256:
    def test_sha256_stored_on_import(self, tmp_path):
        """After import, the stored hash must match the file hash."""
        # Create a fake CV file
        cv_file = tmp_path / "test_cv.txt"
        cv_file.write_text("Name: John Doe\nSkills: Python, SQL")

        # Mock the Gemini call so we don't need a real API key
        import unittest.mock as mock
        mock_profile_data = {
            "full_name": "John Doe", "email": "john@example.com",
            "phone": "", "location": "",
            "github": "", "linkedin": "", "portfolio": "",
            "skills": ["Python", "SQL"], "achievements": [],
            "education": [], "experience": [], "internships": [],
            "projects": [], "certifications": [],
        }

        from app.storage.database import init_db
        from app.utils.config import settings
        init_db()

        with mock.patch("app.parsing.cv_parser._parse_with_gemini", return_value=mock_profile_data):
            from app.parsing.cv_parser import import_cv
            profile = import_cv(cv_file)

        assert profile.master_cv_hash != ""
        assert len(profile.master_cv_hash) == 64
        # Verify the stored hash matches the master copy
        assert verify_file(profile.master_cv_path, profile.master_cv_hash)

    def test_wrong_cv_upload_blocked(self):
        """CV upload gate must reject a file with a different hash."""
        from app.utils.hashing import verify_file
        import tempfile, os
        f1 = _make_temp_file(b"original CV")
        f2 = _make_temp_file(b"different file")
        try:
            original_hash = hash_file(f1)
            # Trying to use f2 where f1 is expected must fail
            assert verify_file(f2, original_hash) is False
        finally:
            os.unlink(f1)
            os.unlink(f2)
