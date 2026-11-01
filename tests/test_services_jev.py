from types import SimpleNamespace

import pytest

from app.services.jev import (
    ClassificationResult,
    ClassifierUnavailable,
    JevClient,
)


class FakeSystemone:
    def __init__(self, noul=0.92, model="typesafe/jev-1.14", error=None):
        self.noul = noul
        self.model = model
        self.error = error
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        if self.error is not None:
            raise self.error
        return SimpleNamespace(
            answers={"is_receipt": SimpleNamespace(noul=self.noul)},
            model=self.model,
        )


def test_classify_calls_litellm_and_parses_score():
    fake = FakeSystemone()
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)

    result = client.classify("aGVsbG8=")

    assert result == ClassificationResult(noul=0.92, model="typesafe/jev-1.14")
    assert fake.kwargs["model"] == "openrouter/typesafe/jev-1.14"
    assert fake.kwargs["api_key"] == "key"
    assert fake.kwargs["timeout"] == 5.0
    assert fake.kwargs["state"] == [
        {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,aGVsbG8="},
        }
    ]
    question = fake.kwargs["questions"]["is_receipt"]
    assert question["type"] == "noul"
    assert question["criteria"]["true"]
    assert question["criteria"]["false"]


def test_classify_emits_call_record_on_success():
    def fake(**kwargs):
        return SimpleNamespace(
            answers={"is_receipt": SimpleNamespace(noul=0.9)},
            model="typesafe/jev-1.14-20261014",
            usage=SimpleNamespace(input_tokens=50, output_tokens=5),
            _hidden_params={"response_cost": 0.0002},
        )

    records = []
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)

    client.classify("aGVsbG8=", on_call=records.append)

    assert len(records) == 1
    assert records[0].provider == "openrouter"
    assert records[0].model == "openrouter/typesafe/jev-1.14"
    assert records[0].input_tokens == 50
    assert records[0].output_tokens == 5
    assert records[0].total_tokens == 55
    assert records[0].cost_usd == 0.0002
    assert records[0].is_error is False


def test_classify_emits_error_record_on_provider_error():
    records = []
    client = JevClient(
        "key",
        "typesafe/jev-1.14",
        systemone_fn=FakeSystemone(error=RuntimeError("provider down")),
    )

    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=", on_call=records.append)

    assert len(records) == 1
    assert records[0].is_error is True
    assert records[0].error == "provider_unavailable"


def test_classify_emits_error_record_on_malformed_response():
    def fake(**kwargs):
        return SimpleNamespace(answers={}, model="typesafe/jev-1.14")

    records = []
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)

    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=", on_call=records.append)

    assert len(records) == 1
    assert records[0].is_error is True
    assert records[0].error == "invalid_response"


def test_classify_emits_error_record_on_invalid_score():
    records = []
    client = JevClient(
        "key",
        "typesafe/jev-1.14",
        systemone_fn=FakeSystemone(noul=1.5),
    )

    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=", on_call=records.append)

    assert len(records) == 1
    assert records[0].is_error is True
    assert records[0].error == "invalid_score"


def test_classify_does_not_double_prefix_model():
    fake = FakeSystemone(noul=0.5)
    client = JevClient("key", "openrouter/typesafe/jev-1.14", systemone_fn=fake)

    client.classify("aGVsbG8=")

    assert fake.kwargs["model"] == "openrouter/typesafe/jev-1.14"


@pytest.mark.parametrize("noul", [-0.1, 1.5, float("nan")])
def test_classify_rejects_invalid_scores(noul):
    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=FakeSystemone(noul=noul))
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


def test_classify_raises_without_api_key():
    client = JevClient("", "typesafe/jev-1.14")
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


def test_classify_raises_on_provider_error():
    client = JevClient(
        "key",
        "typesafe/jev-1.14",
        systemone_fn=FakeSystemone(error=RuntimeError("provider down")),
    )
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")


@pytest.mark.parametrize(
    "response",
    [
        SimpleNamespace(answers={}, model="typesafe/jev-1.14"),
        SimpleNamespace(
            answers={"is_receipt": SimpleNamespace(noul="not-a-number")},
            model="typesafe/jev-1.14",
        ),
    ],
)
def test_classify_raises_on_malformed_response(response):
    def fake(**kwargs):
        return response

    client = JevClient("key", "typesafe/jev-1.14", systemone_fn=fake)
    with pytest.raises(ClassifierUnavailable):
        client.classify("aGVsbG8=")
