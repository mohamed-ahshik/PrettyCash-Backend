from enum import StrEnum


class ErrorCode(StrEnum):
    UNAUTHORIZED = "UNAUTHORIZED"
    INVALID_IMAGE = "INVALID_IMAGE"
    UNPROCESSABLE = "UNPROCESSABLE"
    RATE_LIMITED = "RATE_LIMITED"
    INTERNAL = "INTERNAL"
    NOT_FOUND = "NOT_FOUND"
    NOT_A_RECEIPT = "NOT_A_RECEIPT"
    SUBSCRIPTION_REQUIRED = "SUBSCRIPTION_REQUIRED"
    DAILY_TRIAL_LIMIT_REACHED = "DAILY_TRIAL_LIMIT_REACHED"


class AppError(Exception):
    status_code = 500
    code = ErrorCode.INTERNAL
    default_message = "Internal server error"

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class UnauthorizedError(AppError):
    status_code = 401
    code = ErrorCode.UNAUTHORIZED
    default_message = "Unauthorized"


class InvalidImageError(AppError):
    status_code = 400
    code = ErrorCode.INVALID_IMAGE
    default_message = "Could not read the receipt image"


class UnprocessableError(AppError):
    status_code = 422
    code = ErrorCode.UNPROCESSABLE
    default_message = "Could not process the receipt"


class RateLimitedError(AppError):
    status_code = 429
    code = ErrorCode.RATE_LIMITED
    default_message = "Too many requests"


class InternalError(AppError):
    status_code = 500
    code = ErrorCode.INTERNAL
    default_message = "Internal server error"


class NotFoundError(AppError):
    status_code = 404
    code = ErrorCode.NOT_FOUND
    default_message = "Not found"


class SubscriptionRequiredError(AppError):
    status_code = 403
    code = ErrorCode.SUBSCRIPTION_REQUIRED
    default_message = "A PrettyCash Pro subscription is required"


class DailyTrialLimitError(AppError):
    status_code = 403
    code = ErrorCode.DAILY_TRIAL_LIMIT_REACHED
    default_message = "Daily trial scan limit reached"
