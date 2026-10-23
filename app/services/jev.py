import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

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

    def classify(self, image_base64: str) -> ClassificationResult:
        if not self._api_key:
            raise ClassifierUnavailable("OpenRouter Jev API key is not configured")

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
            raise ClassifierUnavailable("Jev request failed") from exc

        try:
            answer = response.answers["is_receipt"]
            noul = float(answer.noul)
            model = str(getattr(response, "model", "") or self._model)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            raise ClassifierUnavailable("Unexpected Jev response") from exc

        if not math.isfinite(noul) or not 0.0 <= noul <= 1.0:
            raise ClassifierUnavailable("Jev returned an invalid noul score")

        return ClassificationResult(noul=noul, model=model)
