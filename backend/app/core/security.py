"""Access control and limits for the public API.

- API key:   every endpoint except /health needs the X-API-Key header (the apps send it).
- Staff key: listing everyone's reports and changing a report's status need X-Staff-Key too.
- Rate limits per IP address and per device, kept in memory (they reset when the server restarts).

Leave API_KEY empty in .env for local development and the checks are off.
"""
from __future__ import annotations

import hmac
import time
from collections import defaultdict, deque
from threading import Lock
from typing import Optional

from fastapi import Depends, HTTPException, Request
from fastapi.security import APIKeyHeader

from backend.app.core.config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)      # shows an "Authorize" button in /docs
staff_key_header = APIKeyHeader(name="X-Staff-Key", auto_error=False)


def _same(given: Optional[str], expected: str) -> bool:
    return bool(given) and hmac.compare_digest(given.encode(), expected.encode())  # constant time


def require_api_key(request: Request, key: Optional[str] = Depends(api_key_header)) -> None:
    if request.url.path == "/health" or not settings.api_key:
        return
    if not _same(key, settings.api_key):
        raise HTTPException(401, "Missing or wrong API key (send the X-API-Key header)")


def is_staff(key: Optional[str]) -> bool:
    return bool(settings.staff_key) and _same(key, settings.staff_key)


def require_staff(key: Optional[str] = Depends(staff_key_header)) -> None:
    if not is_staff(key):
        raise HTTPException(403, "Staff only (send the X-Staff-Key header)")


def client_ip(request: Request) -> str:
    """Behind the Cloudflare tunnel every request comes from 127.0.0.1, so use the address Cloudflare saw."""
    forwarded = request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for", "").split(",")[0]
    return forwarded.strip() or (request.client.host if request.client else "unknown")


class RateLimiter:
    """Sliding windows: at most `per_minute` and `per_day` hits for each key."""

    def __init__(self, per_minute: int, per_day: int):
        self.per_minute, self.per_day = per_minute, per_day
        self.hits: dict[str, deque] = defaultdict(deque)
        self.lock = Lock()

    def check(self, *keys: str) -> None:
        now = time.time()
        with self.lock:
            for key in keys:
                q = self.hits[key]
                while q and q[0] < now - 86_400:
                    q.popleft()
                last_minute = sum(1 for t in q if t > now - 60)
                if last_minute >= self.per_minute or len(q) >= self.per_day:
                    wait = 60 if last_minute >= self.per_minute else int(q[0] + 86_400 - now) + 1
                    raise HTTPException(429, f"Too many requests - try again in {wait} s",
                                        headers={"Retry-After": str(wait)})
            for key in keys:
                self.hits[key].append(now)


# questions that can run a fresh analysis (Muse Spark, SAM, Google), voice reports, and cheap lookups
ASK_LIMIT = RateLimiter(settings.ask_per_minute, settings.ask_per_day)
REPORT_LIMIT = RateLimiter(settings.reports_per_minute, settings.reports_per_day)
LIGHT_LIMIT = RateLimiter(120, 20_000)


def limited(limiter: RateLimiter):
    """Dependency: count this request against the limiter, per IP and per device (X-Device-Id header)."""
    def dep(request: Request) -> None:
        keys = [f"ip:{client_ip(request)}"]
        device = request.headers.get("x-device-id")
        if device:
            keys.append(f"device:{device[:64]}")
        limiter.check(*keys)
    return dep


class DailyBudget:
    """A cap on paid calls per UTC day (e.g. Google Places)."""

    def __init__(self, per_day: int):
        self.per_day, self.day, self.used, self.lock = per_day, "", 0, Lock()

    def take(self, n: int = 1) -> bool:
        with self.lock:
            today = time.strftime("%Y-%m-%d", time.gmtime())
            if today != self.day:
                self.day, self.used = today, 0
            if self.used + n > self.per_day:
                return False
            self.used += n
            return True


GOOGLE_BUDGET = DailyBudget(settings.google_calls_per_day)
