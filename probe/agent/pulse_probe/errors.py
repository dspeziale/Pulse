"""Formato errore standard della Probe (coerente col DOCUMENTO_API §Errori)."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details: dict[str, Any] = details or {}

    def body(self) -> dict[str, Any]:
        return {"error": {"code": self.code, "message": self.message, "details": self.details}}


def unauthorized(message: str = "Autenticazione non valida.") -> ApiError:
    return ApiError(401, "UNAUTHORIZED", message)


def bad_request(message: str, details: dict[str, Any] | None = None) -> ApiError:
    return ApiError(400, "BAD_REQUEST", message, details)


def not_found(message: str = "Risorsa inesistente.") -> ApiError:
    return ApiError(404, "NOT_FOUND", message)


def service_unavailable(message: str) -> ApiError:
    return ApiError(503, "SERVICE_UNAVAILABLE", message)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api(_: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content=exc.body())

    @app.exception_handler(RequestValidationError)
    async def _val(_: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content={"error": {"code": "UNPROCESSABLE_ENTITY", "message": "Validazione fallita.", "details": {"errors": exc.errors()}}},
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {400: "BAD_REQUEST", 401: "UNAUTHORIZED", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED", 503: "SERVICE_UNAVAILABLE"}
        code = code_map.get(exc.status_code, "ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Errore."
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": code, "message": message, "details": {}}})
