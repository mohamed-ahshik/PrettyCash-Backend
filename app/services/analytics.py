import logging
import math
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.config import Settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LLMCallRecord:
    model: str
    provider: str
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    cost_usd: float | None
    cost_source: str | None
    latency_seconds: float
    is_error: bool = False
    error: str | None = None


class Analytics(Protocol):
    def capture_generation(
        self,
        record: LLMCallRecord,
        *,
        job_id: str,
        span_name: str,
        user_id: str | None = None,
        auto_categorize: bool = False,
    ) -> None: ...


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number):
        return None
    return number


def _integer(value: Any) -> int | None:
    number = _number(value)
    if number is None or number < 0:
        return None
    return int(number)


def _usage_values(
    response: Any,
) -> tuple[int | None, int | None, int | None]:
    usage = getattr(response, "usage", None)
    if usage is None:
        return None, None, None

    usage_dump = usage.model_dump() if hasattr(usage, "model_dump") else {}
    input_tokens = _integer(getattr(usage, "prompt_tokens", None))
    if input_tokens is None:
        input_tokens = _integer(usage_dump.get("prompt_tokens"))
    if input_tokens is None:
        input_tokens = _integer(getattr(usage, "input_tokens", None))
    if input_tokens is None:
        input_tokens = _integer(usage_dump.get("input_tokens"))

    output_tokens = _integer(getattr(usage, "completion_tokens", None))
    if output_tokens is None:
        output_tokens = _integer(usage_dump.get("completion_tokens"))
    if output_tokens is None:
        output_tokens = _integer(getattr(usage, "output_tokens", None))
    if output_tokens is None:
        output_tokens = _integer(usage_dump.get("output_tokens"))

    total_tokens = _integer(getattr(usage, "total_tokens", None))
    if total_tokens is None:
        total_tokens = _integer(usage_dump.get("total_tokens"))
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens

    return input_tokens, output_tokens, total_tokens


def _pricing_table_cost(
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if input_tokens is None or output_tokens is None:
        return None

    import litellm

    model_info = litellm.model_cost.get(model)
    if model_info is None and model.startswith("gemini/"):
        model_info = litellm.model_cost.get(model.removeprefix("gemini/"))
    if not model_info:
        return None

    input_cost = _number(model_info.get("input_cost_per_token"))
    output_cost = _number(model_info.get("output_cost_per_token"))
    if input_cost is None or output_cost is None:
        return None
    return input_tokens * input_cost + output_tokens * output_cost


def _cost_values(
    response: Any,
    model: str,
    input_tokens: int | None,
    output_tokens: int | None,
) -> tuple[float | None, str | None]:
    if response is None:
        return None, None

    hidden_params = getattr(response, "_hidden_params", None) or {}
    cost = _number(hidden_params.get("response_cost"))
    if cost is not None:
        return cost, "litellm"

    usage = getattr(response, "usage", None)
    usage_dump = usage.model_dump() if hasattr(usage, "model_dump") else {}
    cost = _number(usage_dump.get("cost"))
    if cost is not None:
        return cost, "litellm"

    import litellm

    try:
        cost = _number(litellm.completion_cost(completion_response=response))
    except Exception:
        cost = None
    if cost is not None:
        return cost, "pricing_table"

    cost = _pricing_table_cost(model, input_tokens, output_tokens)
    if cost is not None:
        return cost, "pricing_table"
    return None, None


def build_call_record(
    response: Any,
    *,
    model: str,
    provider: str,
    latency_seconds: float,
    error: str | None = None,
) -> LLMCallRecord:
    input_tokens, output_tokens, total_tokens = _usage_values(response)
    cost_usd, cost_source = _cost_values(
        response, model, input_tokens, output_tokens
    )
    return LLMCallRecord(
        model=model,
        provider=provider,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cost_usd=cost_usd,
        cost_source=cost_source,
        latency_seconds=max(0.0, latency_seconds),
        is_error=error is not None,
        error=error,
    )


class PostHogAnalytics:
    def __init__(
        self,
        enabled: bool,
        project_api_key: str,
        host: str,
        environment: str,
        client: Any | None = None,
    ) -> None:
        self._environment = environment
        self._client = client
        if self._client is None and enabled and project_api_key:
            try:
                from posthog import Posthog

                self._client = Posthog(project_api_key, host=host)
            except Exception:
                logger.warning(
                    "PostHog initialization failed; analytics disabled",
                    exc_info=True,
                )
                self._client = None

    @classmethod
    def from_settings(cls, settings: Settings) -> "PostHogAnalytics":
        return cls(
            enabled=settings.posthog_enabled,
            project_api_key=settings.posthog_project_api_key,
            host=settings.posthog_host,
            environment=settings.environment,
        )

    def capture_generation(
        self,
        record: LLMCallRecord,
        *,
        job_id: str,
        span_name: str,
        user_id: str | None = None,
        auto_categorize: bool = False,
    ) -> None:
        if self._client is None:
            return

        is_extraction = span_name == "receipt_extraction"
        input_text = (
            "Receipt extraction request"
            if is_extraction
            else "Receipt classification request"
        )
        output_text = (
            "Structured receipt result"
            if is_extraction
            else "Receipt classification result"
        )
        properties: dict[str, Any] = {
            "$ai_trace_id": job_id,
            "$ai_session_id": job_id,
            "$ai_span_name": span_name,
            "$ai_provider": record.provider,
            "$ai_model": record.model,
            "$ai_input_tokens": record.input_tokens,
            "$ai_output_tokens": record.output_tokens,
            "$ai_total_tokens": record.total_tokens,
            "$ai_total_cost_usd": record.cost_usd,
            "$ai_cost_source": record.cost_source,
            "$ai_latency": record.latency_seconds,
            "$ai_is_error": record.is_error,
            "$ai_input": [{"role": "user", "content": input_text}],
            "$ai_output_choices": (
                [] if record.is_error else [{"role": "assistant", "content": output_text}]
            ),
            "receipt_job_id": job_id,
            "user_id": user_id,
            "environment": self._environment,
            "auto_categorize": auto_categorize,
            "attribution": "user" if user_id else "job_only",
        }
        if record.error:
            properties["$ai_error"] = record.error

        try:
            self._client.capture(
                "$ai_generation",
                distinct_id=user_id or job_id,
                properties=properties,
            )
        except Exception:
            logger.warning("PostHog capture failed; continuing", exc_info=True)

    def flush(self) -> None:
        if self._client is None:
            return
        try:
            self._client.flush(timeout_seconds=5)
        except Exception:
            logger.warning("PostHog flush failed; continuing", exc_info=True)
