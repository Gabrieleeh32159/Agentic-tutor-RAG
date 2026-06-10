from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.shared.logging import get_request_id


class AppError(Exception):
    """Base for domain errors that map to a structured HTTP error envelope."""

    code: str = "APP_ERROR"
    status_code: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class SessionNotFoundError(AppError):
    code = "SESSION_NOT_FOUND"
    status_code = 404


class SessionExpiredError(AppError):
    code = "SESSION_EXPIRED"
    status_code = 410


class DocumentNotFoundError(AppError):
    code = "DOCUMENT_NOT_FOUND"
    status_code = 404


class UnsupportedFileTypeError(AppError):
    code = "UNSUPPORTED_FILE_TYPE"
    status_code = 415


class FileTooLargeError(AppError):
    code = "FILE_TOO_LARGE"
    status_code = 413


class PageLimitExceededError(AppError):
    code = "PAGE_LIMIT_EXCEEDED"
    status_code = 413


class ParseFailedError(AppError):
    code = "PARSE_FAILED"
    status_code = 422


class GuardrailBlockedError(AppError):
    code = "GUARDRAIL_BLOCKED"
    status_code = 400


class ProviderUnavailableError(AppError):
    code = "PROVIDER_UNAVAILABLE"
    status_code = 503


def error_envelope(code: str, message: str) -> dict:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": get_request_id(),
        }
    }


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content=error_envelope(exc.code, exc.message),
        )
