"""tests/unit/test_circuit_breaker.py — Circuit breaker state machine tests."""
import pytest
from unittest.mock import MagicMock, patch
from app.external.circuit_breaker import CircuitBreaker, CBState, FAILURE_THRESHOLD


@pytest.fixture
def mock_redis_cb():
    redis = MagicMock()
    store = {}

    def _get(key):
        return store.get(key)

    def _set(key, val, *args, **kwargs):
        store[key] = val

    def _incr(key):
        store[key] = str(int(store.get(key, "0")) + 1)
        return int(store[key])

    def _delete(key):
        store.pop(key, None)

    redis.get    = MagicMock(side_effect=_get)
    redis.set    = MagicMock(side_effect=_set)
    redis.incr   = MagicMock(side_effect=_incr)
    redis.delete = MagicMock(side_effect=_delete)
    return redis


class TestCircuitBreaker:
    @patch("app.external.circuit_breaker.get_sync_redis")
    def test_starts_closed(self, mock_get_redis, mock_redis_cb):
        mock_get_redis.return_value = mock_redis_cb
        cb = CircuitBreaker("test_service")
        assert cb.get_state() == CBState.CLOSED

    @patch("app.external.circuit_breaker.get_sync_redis")
    def test_successful_call_passes_through(self, mock_get_redis, mock_redis_cb):
        mock_get_redis.return_value = mock_redis_cb
        cb = CircuitBreaker("test_service")
        result = cb.call(lambda: "success")
        assert result == "success"

    @patch("app.external.circuit_breaker.get_sync_redis")
    def test_opens_after_threshold_failures(self, mock_get_redis, mock_redis_cb):
        mock_get_redis.return_value = mock_redis_cb
        cb = CircuitBreaker("test_service")

        for i in range(FAILURE_THRESHOLD):
            with pytest.raises(Exception):
                cb.call(lambda: (_ for _ in ()).throw(Exception("fail")))

        assert cb.get_state() == CBState.OPEN

    @patch("app.external.circuit_breaker.get_sync_redis")
    def test_open_circuit_raises_immediately(self, mock_get_redis, mock_redis_cb):
        from app.core.exceptions import CircuitOpenError
        mock_get_redis.return_value = mock_redis_cb
        cb = CircuitBreaker("test_service")
        # Force open state
        mock_redis_cb.get = MagicMock(return_value="open")
        # Force opened_at to old time so it doesn't move to half-open
        import time

        original_get = mock_redis_cb.get.side_effect
        def smart_get(key):
            if "state" in key:
                return "open"
            if "opened_at" in key:
                return str(time.time())  # just opened → still open
            return None
        mock_redis_cb.get.side_effect = smart_get

        with pytest.raises(CircuitOpenError):
            cb.call(lambda: "should not run")

    @patch("app.external.circuit_breaker.get_sync_redis")
    def test_reset_closes_breaker(self, mock_get_redis, mock_redis_cb):
        mock_get_redis.return_value = mock_redis_cb
        cb = CircuitBreaker("test_service")
        cb.reset()
        assert cb.get_state() == CBState.CLOSED
