"""
ApplyPilot — Profile tools (ADK tool functions).

Handles CV import, profile display, and preference configuration.
"""
from __future__ import annotations

import json

from app.parsing.cv_parser import import_cv, get_master_cv_info
from app.storage.repositories import ProfileRepository
from app.storage.models import CandidateProfile
from app.utils.logging import get_logger, write_audit

logger = get_logger(__name__)


def import_cv_tool(cv_path: str = "") -> str:
    """
    Import the user's CV from a local file path.

    Copies the file to protected storage, calculates SHA-256,
    parses it with Gemini, and stores the candidate profile.
    Supported formats: PDF, DOCX, TXT.

    Args:
        cv_path: Absolute path to the CV file. If empty, uses the
                 DEFAULT_CV_PATH configured in settings.

    Returns:
        A summary of the extracted candidate profile for user verification.
    """
    from app.utils.config import settings
    resolved_path = cv_path.strip() or settings.default_cv_path
    if not resolved_path:
        return (
            "❌ No CV path provided and no DEFAULT_CV_PATH configured. "
            "Please provide the full path to your CV file."
        )
    try:
        profile = import_cv(resolved_path)
        ProfileRepository.save(profile)
        write_audit(agent="profile_agent", action="CV_IMPORTED", result="SUCCESS")

        summary = _format_profile_summary(profile)
        return (
            f"✅ CV imported successfully!\n\n"
            f"SHA-256: {profile.master_cv_hash[:16]}...\n\n"
            f"Extracted Profile:\n{summary}\n\n"
            f"Please verify this information is correct. "
            f"Type 'confirm profile' when ready or tell me what to correct."
        )
    except Exception as exc:
        write_audit(agent="profile_agent", action="CV_IMPORT_FAILED", error=str(exc))
        return f"❌ CV import failed: {exc}"


def show_profile() -> str:
    """
    Display the current candidate profile.

    Returns:
        Formatted candidate profile summary.
    """
    profile = ProfileRepository.load()
    if not profile:
        return "No profile found. Please import your CV first using import_cv_tool."
    return _format_profile_summary(profile)


def update_preferences(
    preferred_roles: list[str] | None = None,
    preferred_locations: list[str] | None = None,
    remote_preference: str | None = None,
    minimum_salary: int | None = None,
    employment_preferences: list[str] | None = None,
) -> str:
    """
    Update job search preferences.

    Args:
        preferred_roles: List of preferred job roles/titles.
        preferred_locations: List of preferred locations.
        remote_preference: 'remote', 'hybrid', 'on-site', or 'any'.
        minimum_salary: Minimum acceptable salary in local currency.
        employment_preferences: List of employment types ('full-time', 'internship', etc.).

    Returns:
        Confirmation of updated preferences.
    """
    profile = ProfileRepository.load()
    if not profile:
        return "No profile found. Please import your CV first."

    if preferred_roles is not None:
        profile.preferred_roles = preferred_roles
    if preferred_locations is not None:
        profile.preferred_locations = preferred_locations
    if remote_preference is not None:
        profile.remote_preference = remote_preference
    if minimum_salary is not None:
        profile.minimum_salary = minimum_salary
    if employment_preferences is not None:
        profile.employment_preferences = employment_preferences

    ProfileRepository.save(profile)
    write_audit(agent="profile_agent", action="PREFERENCES_UPDATED", result="SUCCESS")

    prefs = {
        "preferred_roles": profile.preferred_roles,
        "preferred_locations": profile.preferred_locations,
        "remote_preference": profile.remote_preference,
        "minimum_salary": profile.minimum_salary,
        "employment_preferences": profile.employment_preferences,
    }
    return f"✅ Preferences updated:\n{json.dumps(prefs, indent=2)}"


def change_master_cv(new_cv_path: str) -> str:
    """
    Replace the master CV with a new file.
    This requires EXPLICIT user action — it is not done automatically.
    The new CV gets a new SHA-256 hash.

    Args:
        new_cv_path: Absolute path to the new CV file.

    Returns:
        Confirmation with new CV hash, or error message.
    """
    try:
        profile = import_cv(new_cv_path)
        existing = ProfileRepository.load()
        if existing:
            # Preserve preferences
            profile.preferred_roles = existing.preferred_roles
            profile.preferred_locations = existing.preferred_locations
            profile.remote_preference = existing.remote_preference
            profile.minimum_salary = existing.minimum_salary
            profile.employment_preferences = existing.employment_preferences
        ProfileRepository.save(profile)
        write_audit(agent="profile_agent", action="MASTER_CV_CHANGED", result="SUCCESS")
        return (
            f"✅ Master CV updated.\n"
            f"New file: {profile.master_cv_original_filename}\n"
            f"New SHA-256: {profile.master_cv_hash[:16]}...\n"
        )
    except Exception as exc:
        return f"❌ Failed to change master CV: {exc}"


def get_cv_integrity_status() -> str:
    """
    Verify that the master CV file is intact (SHA-256 check).

    Returns:
        Integrity status message.
    """
    from app.utils.hashing import verify_file
    info = get_master_cv_info()
    if not info:
        return "No master CV on record."
    path = info["storage_path"]
    expected = info["sha256"]
    try:
        ok = verify_file(path, expected)
    except FileNotFoundError:
        return f"❌ CV INTEGRITY CHECK FAILED — file not found at {path}"

    if ok:
        return (
            f"✅ CV Integrity: VERIFIED\n"
            f"File: {info['original_filename']}\n"
            f"SHA-256: {expected[:16]}...\n"
        )
    else:
        return (
            f"❌ CV INTEGRITY CHECK FAILED\n"
            f"File: {info['original_filename']}\n"
            f"Expected hash: {expected[:16]}...\n"
            f"Current hash: MISMATCH\n"
            f"CV upload BLOCKED."
        )


def _format_profile_summary(profile: CandidateProfile) -> str:
    lines = [
        f"Name:     {profile.full_name or 'Unknown'}",
        f"Email:    {profile.email or 'Unknown'}",
        f"Phone:    {profile.phone or 'Unknown'}",
        f"Location: {profile.location or 'Unknown'}",
        f"LinkedIn: {profile.linkedin or '—'}",
        f"GitHub:   {profile.github or '—'}",
        f"",
        f"Skills ({len(profile.skills)}): {', '.join(profile.skills[:15])}{'...' if len(profile.skills) > 15 else ''}",
        f"",
        f"Education ({len(profile.education)}):",
    ]
    for edu in profile.education[:3]:
        lines.append(f"  • {edu.degree} — {edu.institution} ({edu.end_year or 'ongoing'})")

    lines.append(f"\nExperience ({len(profile.experience)}):")
    for exp in profile.experience[:3]:
        lines.append(f"  • {exp.title} @ {exp.company} ({exp.start_date}–{exp.end_date})")

    lines.append(f"\nProjects ({len(profile.projects)}):")
    for proj in profile.projects[:3]:
        lines.append(f"  • {proj.name}: {proj.description[:80]}...")

    lines.append(f"\nPreferences:")
    lines.append(f"  Roles:      {', '.join(profile.preferred_roles) or 'Not set'}")
    lines.append(f"  Locations:  {', '.join(profile.preferred_locations) or 'Not set'}")
    lines.append(f"  Remote:     {profile.remote_preference}")
    lines.append(f"  Employment: {', '.join(profile.employment_preferences) or 'Not set'}")

    return "\n".join(lines)
