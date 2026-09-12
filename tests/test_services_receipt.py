import pytest

from app.core.errors import UnprocessableError
from app.services.receipt import ReceiptAnalyzer


class FakeGemini:
    def __init__(self, payload: dict):
        self.payload = payload

    def analyze(self, image_base64: str, mime_type: str) -> dict:
        return self.payload


def test_normalizes_valid_payload():
    analyzer = ReceiptAnalyzer(FakeGemini({
        "merchant": "Whole Foods",
        "amount": 42.75,
        "date": "2026-09-13",
        "time": "14:30",
        "note": "groceries",
        "items": [{"name": "Almond Milk", "quantity": 2, "price": 6.98}],
    }))
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == "Whole Foods"
    assert draft.amount == 42.75
    assert draft.date == "2026-09-13"
    assert draft.time == "14:30"
    assert draft.note == "groceries"
    assert draft.items[0].name == "Almond Milk"
    assert draft.items[0].quantity == 2
    assert draft.items[0].price == 6.98


def test_defaults_missing_optional_fields():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "", "amount": 10.0}))
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == ""
    assert draft.date is None
    assert draft.time is None
    assert draft.note == ""
    assert draft.items == []


def test_raises_unprocessable_on_missing_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X"}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")


def test_raises_unprocessable_on_negative_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X", "amount": -5}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")
