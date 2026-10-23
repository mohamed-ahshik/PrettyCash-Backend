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
