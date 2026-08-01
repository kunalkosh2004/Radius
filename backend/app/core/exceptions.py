from http import HTTPStatus


class AppError(Exception):
    """Base class for application-level (domain) errors."""

    status_code: int = HTTPStatus.BAD_REQUEST
    detail: str = "an error occurred"


class NicknameAlreadyTakenError(AppError):
    status_code = HTTPStatus.CONFLICT
    detail = "nickname already taken"
