from pydantic import BaseModel, Field

from app.services.receipt import ReceiptDraft


class ImagePayload(BaseModel):
    base64: str
    mimeType: str


class CategoryOption(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=200)


class AnalyzeReceiptRequest(BaseModel):
    image: ImagePayload
    autoCategorize: bool = False
    categories: list[CategoryOption] = Field(default_factory=list, max_length=50)


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
