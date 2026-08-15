"""
ApplyPilot — CV parser.

Workflow:
  1. Accept PDF / DOCX / TXT path.
  2. Extract raw text.
  3. Call Gemini to parse raw text into CandidateProfile JSON.
  4. Copy file to data/cv/master/ (immutable storage).
  5. Compute SHA-256 and persist metadata to DB.
  6. Return populated CandidateProfile.

The uploaded CV is NEVER modified. Only reading / copying is allowed.
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from app.storage.database import get_connection
from app.storage.models import (
    CandidateProfile, Education, Experience, Project, Certification
)
from app.utils.config import settings
from app.utils.hashing import hash_file
from app.utils.logging import get_logger

logger = get_logger(__name__)


# ── Text extraction ───────────────────────────────────────────────────────────

def _extract_text_pdf(path: Path) -> str:
    try:
        import pdfplumber
        with pdfplumber.open(path) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    # Fallback: PyPDF2
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(str(path))
        return "\n".join(p.extract_text() or "" for p in reader.pages)
    except ImportError:
        raise RuntimeError(
            "PDF parsing requires 'pdfplumber' or 'PyPDF2'. "
            "Run: uv add pdfplumber"
        )


def _extract_text_docx(path: Path) -> str:
    try:
        from docx import Document
        doc = Document(str(path))
        return "\n".join(p.text for p in doc.paragraphs)
    except ImportError:
        raise RuntimeError(
            "DOCX parsing requires 'python-docx'. Run: uv add python-docx"
        )


def _extract_text(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _extract_text_pdf(path)
    if suffix in {".docx", ".doc"}:
        return _extract_text_docx(path)
    if suffix in {".txt", ".md", ".rst"}:
        return path.read_text(encoding="utf-8", errors="replace")
    raise ValueError(f"Unsupported CV format: {suffix}. Supported: PDF, DOCX, TXT")


# ── Gemini parsing ────────────────────────────────────────────────────────────

_PARSE_PROMPT = """
You are a precise CV parser. Extract structured information from the CV text below.
Return ONLY valid JSON matching this exact schema (use empty string "" or [] for unknown fields — never invent information):

{{
  "full_name": "",
  "email": "",
  "phone": "",
  "location": "",
  "github": "",
  "linkedin": "",
  "portfolio": "",
  "skills": [],
  "achievements": [],
  "education": [
    {{"institution":"","degree":"","field_of_study":"","start_year":null,"end_year":null,"grade":""}}
  ],
  "experience": [
    {{"company":"","title":"","location":"","start_date":"","end_date":"","responsibilities":[],"is_internship":false}}
  ],
  "internships": [
    {{"company":"","title":"","location":"","start_date":"","end_date":"","responsibilities":[],"is_internship":true}}
  ],
  "projects": [
    {{"name":"","description":"","technologies":[],"url":""}}
  ],
  "certifications": [
    {{"name":"","issuer":"","date":"","url":""}}
  ]
}}

CV TEXT:
{cv_text}

Respond with ONLY the JSON object. No markdown, no explanation.
"""


def _parse_with_gemini(cv_text: str) -> dict:
    """Send CV text to Gemini and return parsed dict."""
    from google import genai
    from google.genai import types as gtypes
    from app.quota.limiter import limiter
    from app.utils.config import settings as cfg

    client = genai.Client(api_key=cfg.gemini_api_key)
    prompt = _PARSE_PROMPT.format(cv_text=cv_text[:15000])  # truncate to avoid huge prompts

    def _call():
        resp = client.models.generate_content(
            model=cfg.gemini_model,
            contents=prompt,
            config=gtypes.GenerateContentConfig(
                temperature=0.0,
                max_output_tokens=4096,
            ),
        )
        return resp

    resp = limiter.with_retry(_call, agent="cv_parser", action="parse_cv")
    text = resp.text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        text = text.split("```")[1]
        if text.startswith("json"):
            text = text[4:]

    return json.loads(text)


def _dict_to_profile(data: dict) -> CandidateProfile:
    profile = CandidateProfile(
        full_name=data.get("full_name", ""),
        email=data.get("email", ""),
        phone=data.get("phone", ""),
        location=data.get("location", ""),
        github=data.get("github", ""),
        linkedin=data.get("linkedin", ""),
        portfolio=data.get("portfolio", ""),
        skills=data.get("skills", []),
        achievements=data.get("achievements", []),
    )
    for edu in data.get("education", []):
        profile.education.append(Education(**{k: edu.get(k, "") for k in Education.__dataclass_fields__}))
    for exp in data.get("experience", []):
        profile.experience.append(Experience(**{k: exp.get(k, v.default if hasattr(v, 'default') else "") for k, v in Experience.__dataclass_fields__.items()}))
    for intern in data.get("internships", []):
        item = Experience(**{k: intern.get(k, "") for k in Experience.__dataclass_fields__ if k != "responsibilities"})
        item.responsibilities = intern.get("responsibilities", [])
        item.is_internship = True
        profile.internships.append(item)
    for proj in data.get("projects", []):
        profile.projects.append(Project(
            name=proj.get("name", ""),
            description=proj.get("description", ""),
            technologies=proj.get("technologies", []),
            url=proj.get("url", ""),
        ))
    for cert in data.get("certifications", []):
        profile.certifications.append(Certification(
            name=cert.get("name", ""),
            issuer=cert.get("issuer", ""),
            date=cert.get("date", ""),
            url=cert.get("url", ""),
        ))
    return profile


# ── Public API ────────────────────────────────────────────────────────────────

def import_cv(cv_path: str | Path) -> CandidateProfile:
    """
    Import the user's CV.

    Steps:
      1. Validate file exists and format is supported.
      2. Extract text.
      3. Parse with Gemini.
      4. Copy to protected master storage.
      5. Calculate SHA-256 and persist metadata.
      6. Return populated CandidateProfile.

    The original file is never modified.
    """
    src = Path(cv_path).resolve()
    if not src.exists():
        raise FileNotFoundError(f"CV file not found: {src}")

    logger.info("Importing CV from %s", src)

    # Extract text
    raw_text = _extract_text(src)
    logger.info("Extracted %d characters from CV", len(raw_text))

    # Parse via Gemini
    parsed = _parse_with_gemini(raw_text)
    profile = _dict_to_profile(parsed)

    # Copy to master storage (protected, immutable)
    settings.cv_master_dir.mkdir(parents=True, exist_ok=True)
    dest = settings.cv_master_dir / src.name
    # If file already there and identical, skip copy
    if not dest.exists() or hash_file(src) != hash_file(dest):
        shutil.copy2(src, dest)
    logger.info("CV stored at %s", dest)

    # Calculate SHA-256 of the master copy
    cv_hash = hash_file(dest)
    file_size = dest.stat().st_size
    now = datetime.now(timezone.utc).isoformat()

    # Persist CV metadata
    with get_connection() as con:
        # Mark all previous as non-master
        con.execute("UPDATE cv_metadata SET is_master=0")
        con.execute(
            """
            INSERT OR REPLACE INTO cv_metadata
              (original_filename, file_size, sha256, storage_path, import_timestamp, is_master)
            VALUES (?,?,?,?,?,1)
            """,
            (src.name, file_size, cv_hash, str(dest), now),
        )

    # Enrich profile with CV file info
    profile.master_cv_path = str(dest)
    profile.master_cv_hash = cv_hash
    profile.master_cv_original_filename = src.name
    profile.master_cv_size = file_size
    profile.master_cv_import_timestamp = now

    logger.info("CV imported successfully | hash=%s", cv_hash[:12] + "...")
    return profile


def get_master_cv_info() -> Optional[dict]:
    """Return current master CV metadata or None."""
    with get_connection() as con:
        row = con.execute(
            "SELECT * FROM cv_metadata WHERE is_master=1 LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return dict(row)
