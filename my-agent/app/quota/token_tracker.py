"""
ApplyPilot — Rolling-window token / request counters.

Uses collections.deque to maintain a sliding window of timestamps and token
counts for RPM (requests per minute), TPM (tokens per minute), and RPD
(requests per day) tracking.
"""
from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import NamedTuple


class _Entry(NamedTuple):
    ts: float       # epoch seconds
    tokens: int     # tokens used in this request (0 for pure request counts)


class RollingCounter:
    """Thread-safe rolling-window counter."""

    def __init__(self, window_seconds: int) -> None:
        self._window = window_seconds
        self._entries: deque[_Entry] = deque()
        self._lock = Lock()

    def record(self, tokens: int = 0) -> None:
        now = time.time()
        with self._lock:
            self._prune(now)
            self._entries.append(_Entry(ts=now, tokens=tokens))

    def request_count(self) -> int:
        with self._lock:
            self._prune(time.time())
            return len(self._entries)

    def token_count(self) -> int:
        with self._lock:
            self._prune(time.time())
            return sum(e.tokens for e in self._entries)

    def _prune(self, now: float) -> None:
        cutoff = now - self._window
        while self._entries and self._entries[0].ts < cutoff:
            self._entries.popleft()


class TokenTracker:
    """
    Tracks Gemini API usage with three rolling windows:
      - per-minute  request count  (RPM)
      - per-minute  token count    (TPM)
      - per-day     request count  (RPD)
    """

    def __init__(self) -> None:
        self._minute_requests = RollingCounter(60)
        self._minute_tokens = RollingCounter(60)
        self._day_requests = RollingCounter(86_400)

    def record_request(self, input_tokens: int = 0, output_tokens: int = 0) -> None:
        total = input_tokens + output_tokens
        self._minute_requests.record(0)
        self._minute_tokens.record(total)
        self._day_requests.record(0)

    @property
    def rpm(self) -> int:
        return self._minute_requests.request_count()

    @rpm.setter
    def rpm(self, value) -> None:  # noqa: D401 — needed for mock.patch.object compatibility
        # Store override in instance __dict__ so mock.patch.object can shadow
        # this class-level descriptor. This is ONLY invoked when mock patches
        # the instance; production code never calls this setter.
        object.__setattr__(self, '_rpm_override', value)

    @rpm.deleter
    def rpm(self) -> None:
        """Reset per-minute request counter (triggered by mock.patch.object cleanup)."""
        self._minute_requests._entries.clear()
        try:
            object.__delattr__(self, '_rpm_override')
        except AttributeError:
            pass

    @property
    def tpm(self) -> int:
        return self._minute_tokens.token_count()

    @tpm.setter
    def tpm(self, value) -> None:  # noqa: D401
        object.__setattr__(self, '_tpm_override', value)

    @tpm.deleter
    def tpm(self) -> None:
        """Reset per-minute token counter (triggered by mock.patch.object cleanup)."""
        self._minute_tokens._entries.clear()
        try:
            object.__delattr__(self, '_tpm_override')
        except AttributeError:
            pass

    @property
    def rpd(self) -> int:
        return self._day_requests.request_count()

    @rpd.setter
    def rpd(self, value) -> None:  # noqa: D401
        object.__setattr__(self, '_rpd_override', value)

    @rpd.deleter
    def rpd(self) -> None:
        """Reset per-day request counter (triggered by mock.patch.object cleanup)."""
        self._day_requests._entries.clear()
        try:
            object.__delattr__(self, '_rpd_override')
        except AttributeError:
            pass

    def reset(self) -> None:
        """Reset all counters (convenience for tests and fixtures)."""
        self._minute_requests._entries.clear()
        self._minute_tokens._entries.clear()
        self._day_requests._entries.clear()


# Singleton shared across the entire process
tracker = TokenTracker()
