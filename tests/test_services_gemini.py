import json
from types import SimpleNamespace

import pytest

from app.core.errors import InternalError
from app.services.gemini import RECEIPT_RESPONSE_SCHEMA, GeminiClient


class FakeCompletion:
    def __init__(self, content=None, response=None, error=None):
        self.content = content
        self.response = response
        self.error = error
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        if self.response is not None:
            return self.response
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=self.content))]
        )


def test_analyze_calls_litellm_and_parses_json():
    payload = json.dumps({"merchant": "Whole Foods", "amount": 42.75})
    fake = FakeCompletion(content=payload)
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)

    result = client.analyze("aGVsbG8=", "image/jpeg")

    assert result == {"merchant": "Whole Foods", "amount": 42.75}
    assert fake.kwargs["model"] == "gemini/gemini-3.1-flash-lite"
    assert fake.kwargs["api_key"] == "key"
    assert fake.kwargs["timeout"] == 60.0
    content = fake.kwargs["messages"][0]["content"]
    assert content[0]["type"] == "text"
    assert "receipt scanner" in content[0]["text"]
    assert content[1] == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="},
    }
    response_format = fake.kwargs["response_format"]
    assert response_format["type"] == "json_object"
    assert response_format["response_schema"] == RECEIPT_RESPONSE_SCHEMA
    assert response_format["response_schema"]["type"] == "object"
    assert "nullable" not in json.dumps(response_format["response_schema"])


def test_analyze_includes_category_prompt_and_schema():
    categories = [
        {
            "key": "c1",
            "id": "uuid-food",
            "name": "Food",
            "description": "Groceries & dining",
        }
    ]
    fake = FakeCompletion(
        content=json.dumps(
            {
                "merchant": "X",
                "amount": 1.0,
                "categoryKey": "c1",
                "categoryConfidence": 0.9,
            }
        )
    )
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)

    client.analyze("aGVsbG8=", "image/jpeg", categories=categories)

    prompt = fake.kwargs["messages"][0]["content"][0]["text"]
    assert '"key": "c1"' in prompt
    assert "Food" in prompt
    assert "Groceries & dining" in prompt
    schema = fake.kwargs["response_format"]["response_schema"]
    assert schema["properties"]["categoryKey"]["anyOf"][0]["enum"] == ["c1"]
    assert schema["properties"]["categoryConfidence"]["maximum"] == 1
    assert "categoryKey" in schema["required"]
    assert "categoryConfidence" in schema["required"]


def test_analyze_emits_call_record_on_success():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(
                    content=json.dumps({"merchant": "X", "amount": 1.0})
                )
            )
        ],
        usage=SimpleNamespace(
            prompt_tokens=100, completion_tokens=20, total_tokens=120
        ),
        _hidden_params={"response_cost": 0.002},
    )
    records = []
    client = GeminiClient(
        "key", "gemini-3.1-flash-lite", completion_fn=FakeCompletion(response=response)
    )

    client.analyze("aGVsbG8=", "image/jpeg", on_call=records.append)

    assert len(records) == 1
    assert records[0].provider == "google"
    assert records[0].model == "gemini/gemini-3.1-flash-lite"
    assert records[0].input_tokens == 100
    assert records[0].output_tokens == 20
    assert records[0].cost_usd == 0.002
    assert records[0].is_error is False


def test_analyze_emits_error_record_on_provider_error():
    records = []
    client = GeminiClient(
        "key",
        "gemini-3.1-flash-lite",
        completion_fn=FakeCompletion(error=RuntimeError("provider down")),
    )

    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg", on_call=records.append)

    assert len(records) == 1
    assert records[0].is_error is True
    assert records[0].error == "provider_unavailable"
    assert records[0].cost_usd is None


def test_analyze_emits_error_record_on_invalid_response():
    records = []
    client = GeminiClient(
        "key",
        "gemini-3.1-flash-lite",
        completion_fn=FakeCompletion(content="not-json"),
    )

    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg", on_call=records.append)

    assert len(records) == 1
    assert records[0].is_error is True
    assert records[0].error == "invalid_response"


def test_analyze_ignores_analytics_callback_failure():
    client = GeminiClient(
        "key",
        "gemini-3.1-flash-lite",
        completion_fn=FakeCompletion(
            content=json.dumps({"merchant": "X", "amount": 1.0})
        ),
    )

    result = client.analyze(
        "aGVsbG8=",
        "image/jpeg",
        on_call=lambda record: (_ for _ in ()).throw(RuntimeError("analytics down")),
    )

    assert result["merchant"] == "X"


def test_analyze_does_not_double_prefix_model():
    fake = FakeCompletion(content=json.dumps({"merchant": "X", "amount": 1.0}))
    client = GeminiClient("key", "gemini/gemini-3.1-flash-lite", completion_fn=fake)

    client.analyze("aGVsbG8=", "image/jpeg")

    assert fake.kwargs["model"] == "gemini/gemini-3.1-flash-lite"


@pytest.mark.parametrize("content", ["", "not-json", None])
def test_analyze_raises_internal_on_bad_content(content):
    client = GeminiClient(
        "key", "gemini-3.1-flash-lite", completion_fn=FakeCompletion(content=content)
    )
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_empty_choices():
    fake = FakeCompletion(response=SimpleNamespace(choices=[]))
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")


def test_analyze_raises_internal_on_provider_error():
    fake = FakeCompletion(error=RuntimeError("provider down"))
    client = GeminiClient("key", "gemini-3.1-flash-lite", completion_fn=fake)
    with pytest.raises(InternalError):
        client.analyze("aGVsbG8=", "image/jpeg")
