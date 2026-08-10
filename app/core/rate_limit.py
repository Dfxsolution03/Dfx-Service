"""
Minimal per-IP rate limiter for unauthenticated, brute-forceable endpoints
(login, forgot-password, reset-password, email-verification request).

Deliberately NOT a general-purpose rate limiting framework and NOT backed by
Redis/slowapi — neither is currently a project dependency. This is a small,
honest in-process token bucket keyed by client IP, appropriate for exactly
one thing: closing the "zero brute-force protection on auth endpoints" gap
found in the security audit.

IMPORTANT CAVEAT — single-instance only:
This limiter's state lives in this process's memory. scripts/entrypoint.sh
defaults APP_WORKERS to 1 (and explicitly warns against raising it without
understanding the async connection-pool implications), so today's
deployment is a single process and this is fully effective. If the
deployment is ever scaled to APP_WORKERS > 1 or multiple Render instances,
each process gets its own independent bucket — the effective limit becomes
(configured limit x process count), and different requests from the same
attacker can land on different processes with no shared state. That would
still slow a brute force by workers-factor, but is no longer a hard cap.
Scaling out safely requires moving this to a shared store (e.g. Redis) —
noted here rather than silently degrading.
"""
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Tuple

from fastapi import Request

from app.exceptions.base import JROSException


class RateLimitExceededException(JROSException):
    def __init__(self, retry_after_seconds: int):
        super().__init__(
            message="Too many requests. Please try again later.",
            code="RATE_LIMIT_EXCEEDED",
            status_code=429,
            errors=[{"code": "RATE_LIMIT_EXCEEDED", "message": f"Retry after {retry_after_seconds}s"}],
        )
        self.retry_after_seconds = retry_after_seconds


class InMemoryIPRateLimiter:
    """Fixed-window-ish limiter: at most `limit` calls per `window_seconds`
    per (bucket_key, client_ip). Old entries are pruned lazily on access, so
    memory stays bounded to recently-active IPs rather than growing forever.
    """

    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window_seconds = window_seconds
        self._hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)

    def _client_ip(self, request: Request) -> str:
        # Render terminates TLS in front of the app and forwards the real
        # client IP via X-Forwarded-For; fall back to the socket peer for
        # local/dev runs where no proxy is present.
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        if request.client:
            return request.client.host
        return "unknown"

    def check(self, request: Request, bucket_key: str) -> None:
        ip = self._client_ip(request)
        key = (bucket_key, ip)
        now = time.monotonic()
        hits = self._hits[key]

        while hits and now - hits[0] > self.window_seconds:
            hits.popleft()

        if len(hits) >= self.limit:
            retry_after = max(1, int(self.window_seconds - (now - hits[0])))
            raise RateLimitExceededException(retry_after)

        hits.append(now)


# Auth endpoints are the brute-force / enumeration / credential-stuffing
# surface: tight limits, short windows. One limiter instance per bucket type
# so login attempts and password-reset requests don't share a budget.
login_rate_limiter = InMemoryIPRateLimiter(limit=10, window_seconds=60)
password_reset_rate_limiter = InMemoryIPRateLimiter(limit=5, window_seconds=300)
email_verification_rate_limiter = InMemoryIPRateLimiter(limit=5, window_seconds=300)


async def rate_limit_login(request: Request) -> None:
    login_rate_limiter.check(request, "login")


async def rate_limit_password_reset(request: Request) -> None:
    password_reset_rate_limiter.check(request, "password_reset")


async def rate_limit_email_verification(request: Request) -> None:
    email_verification_rate_limiter.check(request, "email_verification")
