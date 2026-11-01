import logging
import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from app.services.analytics import LLMCallRecord, build_call_record

logger = logging.getLogger(__name__)

IS_RECEIPT_QUESTION = {
    "is_receipt": {
        "type": "noul",
        "instructions": (
            "The image shows a receipt, bill, or invoice containing merchant and amount "
            "information."
        ),
        "criteria": {
            "true": (
                "A photo, scan, or screenshot of a merchant receipt, bill, or invoice with a "
                "total amount and/or line items."
            ),
            "false": (
                "Any other image, including a selfie, landscape, product photo, unrelated "
                "screenshot, bank statement, order confirmation, or other document without a "
                "merchant receipt or invoice."
            ),
        },
    }
}


class ClassifierUnavailable(Exception):
    """Raised when Jev cannot produce a usable answer; callers fail open to Gemini."""


@dataclass(frozen=True)
class ClassificationResult:
    noul: float
    model: str


def _openrouter_model(model: str) -> str:
    return model if model.startswith("openrouter/") else f"openrouter/{model}"


def _default_systemone(**kwargs: Any) -> Any:
    from litellm import systemone

    return systemone(**kwargs)


def _emit(
    on_call: Callable[[LLMCallRecord], None] | None,
    record: LLMCallRecord,
) -> None:
    if on_call is None:
        return
    try:
        on_call(record)
    except Exception:
        logger.warning("LLM analytics callback failed; continuing", exc_info=True)


class JevClient:
    def __init__(
        self,
        api_key: str,
        model: str,
        timeout: float = 5.0,
        systemone_fn: Callable[..., Any] | None = None,
    ) -> None:
        self._api_key = api_key
        self._model = _openrouter_model(model)
        self._timeout = timeout
        self._systemone = systemone_fn or _default_systemone

    def classify(
        self,
        image_base64: str,
        on_call: Callable[[LLMCallRecord], None] | None = None,
    ) -> ClassificationResult:
        if not self._api_key:
            raise ClassifierUnavailable("OpenRouter Jev API key is not configured")

        started = time.perf_counter()
        try:
            response = self._systemone(
                model=self._model,
                state=[
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{image_base64}",
                        },
                    }
                ],
                questions=IS_RECEIPT_QUESTION,
                api_key=self._api_key,
                timeout=self._timeout,
            )
        except Exception as exc:
            _emit(
                on_call,
                build_call_record(
                    None,
                    model=self._model,
                    provider="openrouter",
                    latency_seconds=time.perf_counter() - started,
                    error="provider_unavailable",
                ),
            )
            raise ClassifierUnavailable("Jev request failed") from exc

        try:
            answer = response.answers["is_receipt"]
            noul = float(answer.noul)
            model = str(getattr(response, "model", "") or self._model)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            _emit(
                on_call,
                build_call_record(
                    response,
                    model=self._model,
                    provider="openrouter",
                    latency_seconds=time.perf_counter() - started,
                    error="invalid_response",
                ),
            )
            raise ClassifierUnavailable("Unexpected Jev response") from exc

        if not math.isfinite(noul) or not 0.0 <= noul <= 1.0:
            _emit(
                on_call,
                build_call_record(
                    response,
                    model=self._model,
                    provider="openrouter",
                    latency_seconds=time.perf_counter() - started,
                    error="invalid_score",
                ),
            )
            raise ClassifierUnavailable("Jev returned an invalid noul score")

        _emit(
            on_call,
            build_call_record(
                response,
                model=self._model,
                provider="openrouter",
                latency_seconds=time.perf_counter() - started,
            ),
        )
        return ClassificationResult(noul=noul, model=model)
