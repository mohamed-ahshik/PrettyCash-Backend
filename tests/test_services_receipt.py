import pytest

from app.core.errors import UnprocessableError
from app.services.receipt import ReceiptAnalyzer


class FakeGemini:
    def __init__(self, payload: dict):
        self.payload = payload
        self.categories = None

    def analyze(
        self,
        image_base64: str,
        mime_type: str,
        categories: list[dict[str, str]] | None = None,
    ) -> dict:
        self.categories = categories
        return self.payload


def _payload(**overrides) -> dict:
    payload = {"merchant": "", "amount": 10.0}
    payload.update(overrides)
    return payload


def test_normalizes_valid_payload():
    analyzer = ReceiptAnalyzer(
        FakeGemini(
            {
                "merchant": "Whole Foods",
                "amount": 42.75,
                "date": "2026-09-13",
                "time": "14:30",
                "note": "groceries",
                "items": [{"name": "Almond Milk", "quantity": 2, "price": 6.98}],
            }
        )
    )
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == "Whole Foods"
    assert draft.amount == 42.75
    assert draft.date == "2026-09-13"
    assert draft.time == "14:30"
    assert draft.note == "groceries"
    assert draft.items[0].name == "Almond Milk"
    assert draft.items[0].quantity == 2
    assert draft.items[0].price == 6.98
    assert draft.categoryId is None
    assert draft.categoryConfidence is None


def test_defaults_missing_optional_fields():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "", "amount": 10.0}))
    draft = analyzer.analyze(b"fake", "image/jpeg")
    assert draft.merchant == ""
    assert draft.date is None
    assert draft.time is None
    assert draft.note == ""
    assert draft.items == []


def test_maps_category_key_to_id_when_confident():
    gemini = FakeGemini(
        _payload(categoryKey="c1", categoryConfidence=0.9)
    )
    analyzer = ReceiptAnalyzer(gemini, category_confidence_threshold=0.7)

    draft = analyzer.analyze(
        b"fake",
        "image/jpeg",
        categories=[{"id": "cat-food", "name": "Food", "description": "Groceries"}],
        auto_categorize=True,
    )

    assert gemini.categories == [
        {
            "key": "c1",
            "id": "cat-food",
            "name": "Food",
            "description": "Groceries",
        }
    ]
    assert draft.categoryId == "cat-food"
    assert draft.categoryConfidence == 0.9


def test_below_threshold_keeps_confidence_without_id():
    analyzer = ReceiptAnalyzer(
        FakeGemini(_payload(categoryKey="c1", categoryConfidence=0.5)),
        category_confidence_threshold=0.7,
    )
    draft = analyzer.analyze(
        b"fake",
        "image/jpeg",
        categories=[{"id": "cat-food", "name": "Food", "description": "Groceries"}],
        auto_categorize=True,
    )
    assert draft.categoryId is None
    assert draft.categoryConfidence == 0.5


@pytest.mark.parametrize(
    "payload",
    [
        _payload(categoryKey=None, categoryConfidence=0),
        _payload(categoryKey="unknown", categoryConfidence=0.9),
        _payload(categoryKey="c1", categoryConfidence=None),
        _payload(categoryKey="c1", categoryConfidence=2),
    ],
)
def test_invalid_category_decision_is_ignored(payload):
    analyzer = ReceiptAnalyzer(
        FakeGemini(payload),
        category_confidence_threshold=0.7,
    )
    draft = analyzer.analyze(
        b"fake",
        "image/jpeg",
        categories=[{"id": "cat-food", "name": "Food", "description": "Groceries"}],
        auto_categorize=True,
    )
    assert draft.categoryId is None


def test_no_categories_skips_category_decision():
    gemini = FakeGemini(_payload(categoryKey="c1", categoryConfidence=0.9))
    analyzer = ReceiptAnalyzer(gemini)

    draft = analyzer.analyze(b"fake", "image/jpeg")

    assert gemini.categories == []
    assert draft.categoryId is None
    assert draft.categoryConfidence is None


def test_raises_unprocessable_on_missing_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X"}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")


def test_raises_unprocessable_on_negative_amount():
    analyzer = ReceiptAnalyzer(FakeGemini({"merchant": "X", "amount": -5}))
    with pytest.raises(UnprocessableError):
        analyzer.analyze(b"fake", "image/jpeg")
