"""Shared rolling-window rate limiting for AutoSkill4Doc LLM calls."""

from __future__ import annotations

from collections import deque
import hashlib
import json
import re
import threading
import time
from typing import Any, Deque, Dict, Optional

from autoskill.llm.base import LLM

AUTOSKILL4DOC_LLM_SCOPE = "autoskill4doc_llm"


class RollingWindowRateLimiter:
    """Thread-safe limiter that bounds requests within one rolling time window."""

    def __init__(self, *, max_requests: int, window_s: float) -> None:
        self.max_requests = max(0, int(max_requests or 0))
        self.window_s = max(0.001, float(window_s or 0.0))
        self._timestamps: Deque[float] = deque()
        self._condition = threading.Condition()
        self._cooldown_until = 0.0
        self._error_streak = 0
        self._last_error_at = 0.0

    def acquire(self) -> None:
        """Blocks until one request slot is available."""

        with self._condition:
            while True:
                now = time.monotonic()
                cooldown_wait = max(0.0, self._cooldown_until - now)
                if cooldown_wait > 0.0:
                    self._condition.wait(timeout=max(0.001, cooldown_wait))
                    continue
                if self.max_requests <= 0:
                    return
                self._prune(now)
                if len(self._timestamps) < self.max_requests:
                    self._timestamps.append(now)
                    return
                oldest = float(self._timestamps[0] or 0.0)
                wait_s = max(0.001, self.window_s - (now - oldest))
                self._condition.wait(timeout=wait_s)

    def record_success(self) -> None:
        """Clears adaptive error streak after a successful request."""

        with self._condition:
            self._error_streak = 0
            self._last_error_at = 0.0
            self._condition.notify_all()

    def record_error(self, exc: Exception) -> None:
        """Applies adaptive cooldown when the exception looks transient."""

        delay_s = _adaptive_retry_delay_seconds(exc)
        if delay_s <= 0.0:
            return
        with self._condition:
            now = time.monotonic()
            if self._last_error_at <= 0.0 or now - self._last_error_at > 60.0:
                self._error_streak = 1
            else:
                self._error_streak += 1
            self._last_error_at = now
            scaled_delay = min(60.0, delay_s * (2 ** max(0, self._error_streak - 1)))
            self._cooldown_until = max(self._cooldown_until, now + scaled_delay)
            self._condition.notify_all()

    def _prune(self, now: float) -> None:
        cutoff = float(now) - self.window_s
        while self._timestamps and self._timestamps[0] <= cutoff:
            self._timestamps.popleft()


class RateLimitedLLM(LLM):
    """Thin LLM wrapper that enforces a shared rolling-window request budget."""

    def __init__(
        self,
        *,
        base_llm: LLM,
        limiter: RollingWindowRateLimiter,
        limiter_key: str,
        max_requests: int,
        window_s: float,
    ) -> None:
        self.base_llm = base_llm
        self.limiter = limiter
        self.limiter_key = str(limiter_key or "").strip()
        self.max_requests = max(0, int(max_requests or 0))
        self.window_s = max(0.0, float(window_s or 0.0))

    def complete(
        self,
        *,
        system: Optional[str],
        user: str,
        temperature: float = 0.0,
    ) -> str:
        self.limiter.acquire()
        try:
            out = self.base_llm.complete(system=system, user=user, temperature=temperature)
        except Exception as exc:
            self.limiter.record_error(exc)
            raise
        self.limiter.record_success()
        return out

    def stream_complete(
        self,
        *,
        system: Optional[str],
        user: str,
        temperature: float = 0.0,
    ):
        self.limiter.acquire()
        try:
            iterator = self.base_llm.stream_complete(system=system, user=user, temperature=temperature)
            for chunk in iterator:
                yield chunk
        except Exception as exc:
            self.limiter.record_error(exc)
            raise
        self.limiter.record_success()


_LIMITERS: Dict[str, RollingWindowRateLimiter] = {}
_LIMITERS_LOCK = threading.Lock()


def _llm_scope_payload(llm_config: Optional[Dict[str, Any]] = None, *, scope: str = "") -> Dict[str, Any]:
    config = dict(llm_config or {})
    return {
        "scope": str(scope or AUTOSKILL4DOC_LLM_SCOPE).strip() or AUTOSKILL4DOC_LLM_SCOPE,
        "provider": str(config.get("provider") or "").strip().lower(),
        "model": str(config.get("model") or "").strip(),
        "base_url": str(config.get("base_url") or config.get("api_base") or "").strip(),
        "auth_mode": str(config.get("auth_mode") or "").strip().lower(),
    }


def llm_rate_limit_key(*, llm_config: Optional[Dict[str, Any]] = None, scope: str = "") -> str:
    """Builds a stable shared limiter key without leaking secrets."""

    payload = _llm_scope_payload(llm_config, scope=scope)
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _shared_limiter(*, key: str, max_requests: int, window_s: float) -> RollingWindowRateLimiter:
    limiter_key = f"{str(key or '').strip()}::{max(0, int(max_requests or 0))}:{max(0.0, float(window_s or 0.0)):.6f}"
    with _LIMITERS_LOCK:
        limiter = _LIMITERS.get(limiter_key)
        if limiter is None:
            limiter = RollingWindowRateLimiter(max_requests=max_requests, window_s=window_s)
            _LIMITERS[limiter_key] = limiter
        return limiter


def maybe_wrap_llm_with_rate_limit(
    llm: Optional[LLM],
    *,
    max_requests: int = 0,
    window_s: float = 0.0,
    llm_config: Optional[Dict[str, Any]] = None,
    scope: str = "",
) -> Optional[LLM]:
    """Wraps one LLM with shared proactive throttling and adaptive cooldowns."""

    if llm is None:
        return None
    safe_max_requests = max(0, int(max_requests or 0))
    safe_window_s = max(0.0, float(window_s or 0.0))
    if isinstance(llm, RateLimitedLLM):
        if llm.max_requests == safe_max_requests and abs(llm.window_s - safe_window_s) < 1e-9:
            return llm
        llm = llm.base_llm
    limiter_key = llm_rate_limit_key(llm_config=llm_config, scope=scope) or f"llm:{llm.__class__.__name__}:{id(llm)}"
    limiter = _shared_limiter(key=limiter_key, max_requests=safe_max_requests, window_s=safe_window_s)
    return RateLimitedLLM(
        base_llm=llm,
        limiter=limiter,
        limiter_key=limiter_key,
        max_requests=safe_max_requests,
        window_s=safe_window_s,
    )


def _extract_retry_after_seconds(text: str) -> float:
    """Best-effort parsing for retry-after hints embedded in provider errors."""

    raw = str(text or "").strip().lower()
    if not raw:
        return 0.0
    patterns = (
        r"retry[- ]after[:=]?\s*(\d+(?:\.\d+)?)\s*(ms|millisecond|milliseconds|s|sec|secs|second|seconds|m|min|mins|minute|minutes)?",
        r"try again in\s*(\d+(?:\.\d+)?)\s*(ms|millisecond|milliseconds|s|sec|secs|second|seconds|m|min|mins|minute|minutes)?",
    )
    for pattern in patterns:
        match = re.search(pattern, raw)
        if not match:
            continue
        value = float(match.group(1) or 0.0)
        unit = str(match.group(2) or "s").strip().lower()
        if unit.startswith("ms"):
            return max(0.0, value / 1000.0)
        if unit.startswith("m"):
            return max(0.0, value * 60.0)
        return max(0.0, value)
    return 0.0


def _adaptive_retry_delay_seconds(exc: Exception) -> float:
    """Returns one base adaptive cooldown for transient provider-side failures."""

    raw = str(exc or "").strip().lower()
    if not raw:
        return 0.0
    retry_after = _extract_retry_after_seconds(raw)
    if retry_after > 0.0:
        return min(60.0, retry_after)
    if any(token in raw for token in ("429", "too many requests", "rate limit", "rate-limit", "quota exceeded", "throttle")):
        return 1.0
    if any(token in raw for token in ("overload", "service unavailable", "temporarily unavailable", "503", "502", "504", "bad gateway", "gateway timeout")):
        return 0.75
    if any(token in raw for token in ("timeout", "timed out", "ssl", "tls", "connection reset", "connection aborted", "connection refused", "remote disconnected", "connection closed", "eof")):
        return 0.5
    return 0.0


def retryable_llm_backoff_seconds(exc: Exception) -> float:
    """Returns the base retry backoff for transient LLM/provider failures."""

    return _adaptive_retry_delay_seconds(exc)


def is_retryable_llm_error(exc: Exception) -> bool:
    """Returns whether the provider error looks transient and worth retrying."""

    return retryable_llm_backoff_seconds(exc) > 0.0
