import litellm

from app.services.analytics import (
    LLMCallRecord,
    PostHogAnalytics,
    build_call_record,
)


class FakeUsage:
    def __init__(self, **values):
        self._values = values

    def model_dump(self):
        return self._values


class FakeResponse:
    def __init__(self, usage=None, hidden=None):
        if usage is not None:
            self.usage = usage
        self._hidden_params = hidden or {}


class FakePostHogClient:
    def __init__(self, error=None):
        self.calls = []
        self.error = error

    def capture(self, event, **kwargs):
        if self.error is not None:
            raise self.error
        self.calls.append((event, kwargs))

    def flush(self, timeout_seconds=None):
        return None


def test_builds_chat_record_with_litellm_cost():
    response = FakeResponse(
        usage=FakeUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        hidden={"response_cost": 0.00123},
    )

    record = build_call_record(
        response,
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        latency_seconds=1.5,
    )

    assert record.input_tokens == 100
    assert record.output_tokens == 20
    assert record.total_tokens == 120
    assert record.cost_usd == 0.00123
    assert record.cost_source == "litellm"
    assert record.is_error is False


def test_builds_decisions_record_with_provider_cost():
    response = FakeResponse(
        usage=FakeUsage(input_tokens=50, output_tokens=5, cost=0.0002),
    )

    record = build_call_record(
        response,
        model="openrouter/typesafe/jev-1.14",
        provider="openrouter",
        latency_seconds=0.4,
    )

    assert record.input_tokens == 50
    assert record.output_tokens == 5
    assert record.total_tokens == 55
    assert record.cost_usd == 0.0002
    assert record.cost_source == "litellm"


def test_pricing_table_fallback(monkeypatch):
    response = FakeResponse(
        usage=FakeUsage(prompt_tokens=1000, completion_tokens=100, total_tokens=1100),
    )

    def fail_cost(**kwargs):
        raise RuntimeError("not mapped")

    monkeypatch.setattr(litellm, "completion_cost", fail_cost)

    record = build_call_record(
        response,
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        latency_seconds=1.0,
    )

    assert record.cost_usd is not None
    assert record.cost_source == "pricing_table"


def test_unknown_cost_stays_null():
    response = FakeResponse(
        usage=FakeUsage(prompt_tokens=10, completion_tokens=2, total_tokens=12),
    )

    record = build_call_record(
        response,
        model="unknown/provider-model",
        provider="unknown",
        latency_seconds=0.1,
    )

    assert record.cost_usd is None
    assert record.cost_source is None


def test_error_record_without_response_has_null_cost():
    record = build_call_record(
        None,
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        latency_seconds=0.2,
        error="provider_unavailable",
    )

    assert record.input_tokens is None
    assert record.cost_usd is None
    assert record.is_error is True
    assert record.error == "provider_unavailable"


def test_capture_generation_payload_has_no_receipt_content():
    client = FakePostHogClient()
    analytics = PostHogAnalytics(True, "key", "host", "test", client=client)
    record = LLMCallRecord(
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        input_tokens=100,
        output_tokens=20,
        total_tokens=120,
        cost_usd=0.001,
        cost_source="litellm",
        latency_seconds=1.2,
    )

    analytics.capture_generation(
        record,
        job_id="job-1",
        span_name="receipt_extraction",
        auto_categorize=True,
    )

    event, kwargs = client.calls[0]
    assert event == "$ai_generation"
    assert kwargs["distinct_id"] == "job-1"
    properties = kwargs["properties"]
    assert properties["$ai_trace_id"] == "job-1"
    assert properties["$ai_session_id"] == "job-1"
    assert properties["$ai_span_name"] == "receipt_extraction"
    assert properties["$ai_provider"] == "google"
    assert properties["$ai_model"] == "gemini/gemini-3.1-flash-lite"
    assert properties["$ai_input_tokens"] == 100
    assert properties["$ai_output_tokens"] == 20
    assert properties["$ai_total_cost_usd"] == 0.001
    assert properties["user_id"] is None
    assert properties["attribution"] == "job_only"
    assert properties["auto_categorize"] is True
    assert "receipt image" not in str(properties).lower()
    assert "merchant" not in properties


def test_capture_generation_uses_user_id_when_present():
    client = FakePostHogClient()
    analytics = PostHogAnalytics(True, "key", "host", "test", client=client)
    record = LLMCallRecord(
        model="openrouter/typesafe/jev-1.14",
        provider="openrouter",
        input_tokens=10,
        output_tokens=1,
        total_tokens=11,
        cost_usd=None,
        cost_source=None,
        latency_seconds=0.3,
        is_error=True,
        error="provider_error",
    )

    analytics.capture_generation(
        record,
        job_id="job-1",
        span_name="receipt_classification",
        user_id="user-1",
    )

    _, kwargs = client.calls[0]
    assert kwargs["distinct_id"] == "user-1"
    assert kwargs["properties"]["user_id"] == "user-1"
    assert kwargs["properties"]["attribution"] == "user"
    assert kwargs["properties"]["$ai_is_error"] is True
    assert kwargs["properties"]["$ai_error"] == "provider_error"
    assert kwargs["properties"]["$ai_output_choices"] == []


def test_capture_failure_is_isolated():
    client = FakePostHogClient(error=RuntimeError("posthog down"))
    analytics = PostHogAnalytics(True, "key", "host", "test", client=client)
    record = LLMCallRecord(
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        input_tokens=1,
        output_tokens=1,
        total_tokens=2,
        cost_usd=None,
        cost_source=None,
        latency_seconds=0.1,
    )

    analytics.capture_generation(record, job_id="job-1", span_name="receipt_extraction")


def test_initialization_failure_is_isolated(monkeypatch):
    import posthog

    def fail(*args, **kwargs):
        raise RuntimeError("bad host")

    monkeypatch.setattr(posthog, "Posthog", fail)

    analytics = PostHogAnalytics(True, "key", "host", "test")
    record = LLMCallRecord(
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        cost_usd=None,
        cost_source=None,
        latency_seconds=0.1,
    )

    analytics.capture_generation(record, job_id="job-1", span_name="receipt_extraction")


def test_disabled_analytics_is_a_noop():
    analytics = PostHogAnalytics(False, "", "host", "test")
    record = LLMCallRecord(
        model="gemini/gemini-3.1-flash-lite",
        provider="google",
        input_tokens=None,
        output_tokens=None,
        total_tokens=None,
        cost_usd=None,
        cost_source=None,
        latency_seconds=0.1,
    )

    analytics.capture_generation(record, job_id="job-1", span_name="receipt_extraction")
    analytics.flush()
