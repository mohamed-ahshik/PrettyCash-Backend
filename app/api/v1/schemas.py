from pydantic import BaseModel

from app.services.receipt import ReceiptDraft


class ImagePayload(BaseModel):
    base64: str
    mimeType: str


class AnalyzeReceiptRequest(BaseModel):
    image: ImagePayload


class AnalyzeReceiptAccepted(BaseModel):
    jobId: str
    status: str


class JobError(BaseModel):
    code: str
    message: str


class JobStatusResponse(BaseModel):
    status: str
    result: ReceiptDraft | None = None
    error: JobError | None = None
