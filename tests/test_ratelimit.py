import fakeredis
import pytest

from app.core.errors import RateLimitedError
from app.services.ratelimit import RedisRateLimiter


def test_allows_up_to_limit():
    r = fakeredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(r, per_minute=2)
    limiter.check("k")
    limiter.check("k")
    with pytest.raises(RateLimitedError):
        limiter.check("k")


def test_isolates_keys():
    r = fakeredis.FakeRedis(decode_responses=True)
    limiter = RedisRateLimiter(r, per_minute=1)
    limiter.check("a")
    limiter.check("b")
