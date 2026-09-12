import pytest

from app.api.deps import RateLimiter
from app.core.errors import RateLimitedError


def test_rate_limiter_allows_up_to_limit():
    limiter = RateLimiter(per_minute=2)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(RateLimitedError):
        limiter.check("k")


def test_rate_limiter_isolates_keys():
    limiter = RateLimiter(per_minute=1)
    limiter.check("a")
    limiter.check("b")  # different key, allowed
