import base64
import io

from PIL import Image, ImageOps

from app.services.jev import ClassificationResult, ClassifierUnavailable, JevClient

MIN_SIDE = 256
MAX_SIDE = 1568
MIN_PIXELS = 78_400


class ReceiptClassifier:
    def __init__(self, jev: JevClient) -> None:
        self._jev = jev

    def classify(self, image_bytes: bytes) -> ClassificationResult:
        return self._jev.classify(self._to_jev_base64(image_bytes))

    def _to_jev_base64(self, image_bytes: bytes) -> str:
        try:
            image = Image.open(io.BytesIO(image_bytes))
            image.load()
        except Exception as exc:
            raise ClassifierUnavailable("Could not decode image for classification") from exc

        image = ImageOps.exif_transpose(image)
        if image.mode != "RGB":
            image = image.convert("RGB")

        width, height = image.size
        if min(width, height) < MIN_SIDE or width * height < MIN_PIXELS:
            raise ClassifierUnavailable("Image is too small for Jev")

        if max(width, height) > MAX_SIDE:
            image.thumbnail((MAX_SIDE, MAX_SIDE))

        buffer = io.BytesIO()
        image.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode()
