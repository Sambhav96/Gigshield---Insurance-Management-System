"""external/circuit_breaker.py — Redis-backed circuit breaker per external dependency."""
from __future__ import annotations

import time
from enum import Enum
from typing import Callable, Any

import structlog

from app.core.redis_client import get_sync_redis
from app.core.exceptions import CircuitOpenError

log = structlog.get_logger()

FAILURE_THRESHOLD = 5
SUCCESS_THRESHOLD = 2
TIMEOUT_SECONDS = 60  # half-open window


class CBState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """
    Redis-backed circuit breaker.
    States: CLOSED → (failures > threshold) → OPEN → (timeout elapsed) → HALF_OPEN
            HALF_OPEN → (success) → CLOSED | (failure) → OPEN
    """

    def __init__(self, service_name: str):
        self.service_name = service_name
        self._redis_prefix = f"cb:{service_name}"

    @property
    def _redis(self):
        return get_sync_redis()

    def _key(self, suffix: str) -> str:
        return f"{self._redis_prefix}:{suffix}"

    def get_state(self) -> CBState:
        state = self._redis.get(self._key("state"))
        return CBState(state) if state else CBState.CLOSED

    def _set_state(self, state: CBState) -> None:
        self._redis.set(self._key("state"), state.value)
        log.info("circuit_breaker_state_change", service=self.service_name, state=state.value)

    def call(self, func: Callable, *args, **kwargs) -> Any:
        state = self.get_state()

        if state == CBState.OPEN:
            # Check if timeout elapsed → move to HALF_OPEN
            opened_at = self._redis.get(self._key("opened_at"))
            if opened_at and (time.time() - float(opened_at)) > TIMEOUT_SECONDS:
                self._set_state(CBState.HALF_OPEN)
                self._redis.set(self._key("half_open_successes"), 0)
            else:
                raise CircuitOpenError(
                    f"Circuit breaker OPEN for {self.service_name}",
                    {"service": self.service_name},
                )

        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except CircuitOpenError:
            raise
        except Exception as exc:
            self._on_failure(str(exc))
            raise

    def _on_success(self) -> None:
        state = self.get_state()
        if state == CBState.HALF_OPEN:
            successes = self._redis.incr(self._key("half_open_successes"))
            if int(successes) >= SUCCESS_THRESHOLD:
                self._set_state(CBState.CLOSED)
                self._redis.delete(self._key("failures"))
                self._redis.delete(self._key("opened_at"))
        elif state == CBState.CLOSED:
            self._redis.delete(self._key("failures"))

    def _on_failure(self, error: str) -> None:
        state = self.get_state()
        if state == CBState.HALF_OPEN:
            self._set_state(CBState.OPEN)
            self._redis.set(self._key("opened_at"), str(time.time()))
            return

        failures = self._redis.incr(self._key("failures"))
        if int(failures) >= FAILURE_THRESHOLD:
            self._set_state(CBState.OPEN)
            self._redis.set(self._key("opened_at"), str(time.time()))
            log.error(
                "circuit_breaker_opened",
                service=self.service_name,
                failures=failures,
                error=error,
            )

    def reset(self) -> None:
        """Admin: manually reset circuit breaker to CLOSED."""
        self._redis.delete(self._key("state"))
        self._redis.delete(self._key("failures"))
        self._redis.delete(self._key("opened_at"))
        log.info("circuit_breaker_reset", service=self.service_name)


# ─── Singletons per service ───────────────────────────────────────────────────
_breakers: dict[str, CircuitBreaker] = {}


def get_circuit_breaker(service_name: str) -> CircuitBreaker:
    if service_name not in _breakers:
        _breakers[service_name] = CircuitBreaker(service_name)
    return _breakers[service_name]
