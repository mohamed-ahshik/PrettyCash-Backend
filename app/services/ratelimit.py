from app.core.errors import RateLimitedError

RATE_LIMIT_KEY = "rate_limit:{key}"
RATE_LIMIT_WINDOW_SECONDS = 60


class RedisRateLimiter:
    def __init__(self, redis_client, per_minute: int) -> None:
        self._redis = redis_client
        self._per_minute = per_minute

    def check(self, key: str) -> None:
        redis_key = RATE_LIMIT_KEY.format(key=key)
        count = self._redis.incr(redis_key)
        if count == 1:
            self._redis.expire(redis_key, RATE_LIMIT_WINDOW_SECONDS)
        if count > self._per_minute:
            raise RateLimitedError("Rate limit exceeded")
