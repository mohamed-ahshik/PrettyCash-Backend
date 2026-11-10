import secrets
from typing import Any

from fastapi import Depends, Request

from app.core.errors import UnauthorizedError
from app.services.quota import Entitlement


def require_api_key(request: Request) -> str:
    token = request.headers.get("X-API-Key")
    if not token:
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            token = header[len("Bearer "):]
    expected = request.app.state.settings.vision_api_key
    if not token or not secrets.compare_digest(token, expected):
        raise UnauthorizedError("Invalid API key")
    return token


def require_user(request: Request) -> Any:
    header = request.headers.get("Authorization")
    if not header or not header.startswith("Bearer "):
        raise UnauthorizedError("Missing or malformed Authorization header")
    token = header[len("Bearer "):]
    client = getattr(request.app.state, "supabase", None)
    if client is None:
        raise UnauthorizedError("Authentication is not configured")
    try:
        response = client.auth.get_user(token)
    except Exception as exc:
        raise UnauthorizedError("Invalid or expired session") from exc
    user = getattr(response, "user", None)
    if not user:
        raise UnauthorizedError("Invalid or expired session")
    return user


def require_scan_access(
    request: Request,
    user: Any = Depends(require_user),
) -> Entitlement:
    return request.app.state.quota.consume_scan(str(user.id))


def require_rate_limit(request: Request, token: str = Depends(require_api_key)) -> str:
    request.app.state.rate_limiter.check(token)
    return token
