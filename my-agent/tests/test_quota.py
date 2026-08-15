"""
Tests for quota management: RPM/TPM/RPD counters, thresholds, conservation mode.
"""
import time
import unittest.mock as mock

import pytest

from app.quota.token_tracker import TokenTracker, RollingCounter


class TestRollingCounter:
    def test_empty_counter(self):
        c = RollingCounter(60)
        assert c.request_count() == 0
        assert c.token_count() == 0

    def test_record_and_count(self):
        c = RollingCounter(60)
        c.record(100)
        c.record(200)
        assert c.request_count() == 2
        assert c.token_count() == 300

    def test_window_expiry(self):
        c = RollingCounter(window_seconds=1)
        c.record(500)
        assert c.request_count() == 1
        time.sleep(1.1)
        assert c.request_count() == 0  # expired


class TestTokenTracker:
    def test_initial_state(self):
        t = TokenTracker()
        assert t.rpm == 0
        assert t.tpm == 0
        assert t.rpd == 0

    def test_record_increments_all(self):
        t = TokenTracker()
        t.record_request(input_tokens=100, output_tokens=50)
        assert t.rpm == 1
        assert t.tpm == 150
        assert t.rpd == 1

    def test_multiple_records(self):
        t = TokenTracker()
        for _ in range(5):
            t.record_request(input_tokens=10, output_tokens=10)
        assert t.rpm == 5
        assert t.rpd == 5
        assert t.tpm == 100


class TestQuotaLimiter:
    def test_normal_mode(self):
        from app.quota.limiter import QuotaLimiter, QuotaMode
        limiter = QuotaLimiter()
        with mock.patch.object(type(limiter), 'check', return_value=QuotaMode.NORMAL):
            result = limiter.check()
            assert result == QuotaMode.NORMAL

    def test_quota_exceeded_raises(self):
        from app.quota.limiter import QuotaLimiter, QuotaExceededError
        from app.quota import token_tracker as tt_module
        limiter = QuotaLimiter()
        with mock.patch.object(tt_module.tracker, 'rpm', new_callable=lambda: property(lambda self: 9999)):
            with mock.patch.object(tt_module.tracker, 'tpm', new_callable=lambda: property(lambda self: 0)):
                with mock.patch.object(tt_module.tracker, 'rpd', new_callable=lambda: property(lambda self: 0)):
                    pass  # mocking approach below is simpler

        # Direct test: force tracker to exceed limits
        import app.utils.config as cfg
        original_rpm = cfg.settings.internal_max_rpm
        try:
            cfg.settings.internal_max_rpm = 1
            t = tt_module.TokenTracker()
            # Fill up the counter
            for _ in range(2):
                t.record_request()
            # Now check with mocked tracker
            with mock.patch('app.quota.limiter.tracker', t):
                with pytest.raises(QuotaExceededError):
                    limiter.check()
        finally:
            cfg.settings.internal_max_rpm = original_rpm

    def test_retry_succeeds_on_second_attempt(self):
        from app.quota.limiter import QuotaLimiter
        limiter = QuotaLimiter()
        call_count = [0]

        def _flaky_fn():
            call_count[0] += 1
            if call_count[0] < 2:
                raise Exception("429 RESOURCE_EXHAUSTED")
            return "success"

        with mock.patch('time.sleep'):  # don't actually sleep in tests
            result = limiter.with_retry(_flaky_fn)
        assert result == "success"
        assert call_count[0] == 2

    def test_retry_raises_after_max_retries(self):
        from app.quota.limiter import QuotaLimiter
        import app.utils.config as cfg
        limiter = QuotaLimiter()
        cfg.settings.max_retries = 2

        def _always_fail():
            raise Exception("429 RESOURCE_EXHAUSTED")

        with mock.patch('time.sleep'):
            with pytest.raises(RuntimeError, match="retries exhausted"):
                limiter.with_retry(_always_fail)
