import base64
import binascii
import io

from PIL import Image, ImageOps

from app.core.config import Settings
from app.core.errors import InvalidImageError

try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:  # pragma: no cover - pillow-heif is a required dep; this is defensive
    pass

ALLOWED_FORMATS = {"JPEG", "PNG", "WEBP", "HEIF"}


def decode_and_process(base64_data: str, settings: Settings) -> tuple[bytes, str]:
    try:
        raw = base64.b64decode(base64_data, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise InvalidImageError("Image is not valid base64") from exc

    if len(raw) > settings.max_image_bytes:
        raise InvalidImageError("Image is too large")

    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:
        raise InvalidImageError("Could not decode the image") from exc

    if image.format not in ALLOWED_FORMATS:
        raise InvalidImageError(f"Unsupported image format: {image.format}")

    image = ImageOps.exif_transpose(image)
    image.thumbnail((settings.max_image_dimension, settings.max_image_dimension))

    if image.mode in ("RGBA", "LA", "P"):
        image = image.convert("RGB")

    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", quality=85)
    return buffer.getvalue(), "image/jpeg"
