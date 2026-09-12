import json

import httpx
import pytest
import respx

from app.core.errors import InternalError
from app.services.gemini import GeminiClient

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-lite"
    ":generateContent"
)


def _candidates(text: str) -> dict:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


def test_analyze_returns_parsed_json():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        route = respx.post(GEMINI_URL).mock(
            return_value=httpx.Response(
                200, json=_candidates(json.dumps({"merchant": "Whole Foods", "amount": 42.75}))
            )
        )
        result = client.analyze("aGVsbG8=", "image/jpeg")

    assert result == {"merchant": "Whole Foods", "amount": 42.75}
    assert route.called


def test_analyze_raises_internal_on_provider_error():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(500))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_malformed_body():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(return_value=httpx.Response(200, json={"unexpected": True}))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_network_error():
    client = GeminiClient("key", "gemini-3.1-flash-lite")
    with respx.mock:
        respx.post(GEMINI_URL).mock(side_effect=httpx.ConnectError("boom"))
        with pytest.raises(InternalError):
            client.analyze("aGVsbG8=", "image/jpeg")
