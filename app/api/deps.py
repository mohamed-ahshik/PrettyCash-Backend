import secrets

from fastapi import Depends, Request

from app.core.errors import UnauthorizedError


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
