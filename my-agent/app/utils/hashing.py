"""
ApplyPilot — SHA-256 hashing utilities.
"""
from __future__ import annotations

import hashlib
from pathlib import Path


def hash_file(path: str | Path) -> str:
    """Return the SHA-256 hex digest of a file. Reads in 64 KB chunks."""
    sha = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            sha.update(chunk)
    return sha.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Return the SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def verify_file(path: str | Path, expected_hash: str) -> bool:
    """Return True if the file's current SHA-256 matches expected_hash."""
    return hash_file(path) == expected_hash
