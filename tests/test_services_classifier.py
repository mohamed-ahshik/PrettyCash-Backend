import base64
import io

import pytest
from PIL import Image

from app.services.classifier import ReceiptClassifier
from app.services.jev import ClassificationResult, ClassifierUnavailable


class FakeJev:
    def __init__(self):
        self.image_base64 = None

    def classify(self, image_base64: str) -> ClassificationResult:
        self.image_base64 = image_base64
        return ClassificationResult(noul=0.9, model="typesafe/jev-1.14")


def _image_bytes(size=(600, 900), fmt="JPEG") -> bytes:
    img = Image.new("RGB", size, "white")
    buf = io.BytesIO()
    img.save(buf, format=fmt)
    return buf.getvalue()


def test_downscales_to_jev_max_side():
    jev = FakeJev()

    ReceiptClassifier(jev).classify(_image_bytes((1600, 1200)))

    sent = Image.open(io.BytesIO(base64.b64decode(jev.image_base64)))
    assert max(sent.size) <= 1568
    assert min(sent.size) >= 256
    assert sent.size[0] * sent.size[1] >= 78_400


@pytest.mark.parametrize("size", [(200, 200), (256, 300)])
def test_skips_images_outside_jev_size_window(size):
    jev = FakeJev()

    with pytest.raises(ClassifierUnavailable):
        ReceiptClassifier(jev).classify(_image_bytes(size))

    assert jev.image_base64 is None


def test_encodes_jpeg_data():
    jev = FakeJev()

    ReceiptClassifier(jev).classify(_image_bytes((600, 900), fmt="PNG"))

    raw = base64.b64decode(jev.image_base64)
    assert raw[:2] == b"\xff\xd8"


def test_raises_on_undecodable_image():
    jev = FakeJev()

    with pytest.raises(ClassifierUnavailable):
        ReceiptClassifier(jev).classify(b"not an image")
