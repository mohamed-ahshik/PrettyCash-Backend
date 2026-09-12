import secrets
import threading
import time
from collections import deque

from fastapi import Depends, Request

from app.core.errors import RateLimitedError, UnauthorizedError


class RateLimiter:
    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._buckets: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            bucket = self._buckets.setdefault(key, deque())
            while bucket and now - bucket[0] > 60.0:
                bucket.popleft()
            if len(bucket) >= self._per_minute:
                raise RateLimitedError("Rate limit exceeded")
            bucket.append(now)


def require_api_key(request: Request) -> str:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")
    token = header[len("Bearer "):]
    expected = request.app.state.settings.vision_api_key
    if not secrets.compare_digest(token, expected):
        raise UnauthorizedError("Invalid API key")
    return token


def require_rate_limit(request: Request, token: str = Depends(require_api_key)) -> str:
    request.app.state.rate_limiter.check(token)
    return token
