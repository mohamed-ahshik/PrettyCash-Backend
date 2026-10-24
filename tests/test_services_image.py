import base64
import io

import pytest
from PIL import Image

from app.core.config import Settings
from app.core.errors import InvalidImageError
from app.services.image import decode_and_process


def _settings(**overrides) -> Settings:
    values = {
        "gemini_api_key": "g",
        "vision_api_key": "v",
        "redis_url": "redis://localhost:6379/0",
        "supabase_url": "https://example.supabase.co",
        "supabase_service_role_key": "key",
    }
    values.update(overrides)
    return Settings(**values)


def _png_base64(size=(200, 100)) -> str:
    img = Image.new("RGB", size, "red")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


def test_decodes_and_reencodes_to_jpeg():
    data, mime = decode_and_process(_png_base64(), _settings())
    assert mime == "image/jpeg"
    assert data[:2] == b"\xff\xd8"


def test_downscales_large_image():
    data, _ = decode_and_process(_png_base64((4000, 2000)), _settings())
    img = Image.open(io.BytesIO(data))
    assert max(img.size) <= 1600


def test_rejects_invalid_base64():
    with pytest.raises(InvalidImageError):
        decode_and_process("!!!not-base64!!!", _settings())


def test_rejects_non_image_bytes():
    with pytest.raises(InvalidImageError):
        decode_and_process(base64.b64encode(b"hello").decode(), _settings())


def test_rejects_oversized_image():
    settings = _settings(max_image_bytes=10)
    with pytest.raises(InvalidImageError):
        decode_and_process(_png_base64(), settings)


def test_applies_exif_orientation():
    img = Image.new("RGB", (200, 100), "red")
    exif = Image.Exif()
    exif[274] = 6
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    data, _ = decode_and_process(base64.b64encode(buf.getvalue()).decode(), _settings())

    out = Image.open(io.BytesIO(data))
    assert out.size == (100, 200)
