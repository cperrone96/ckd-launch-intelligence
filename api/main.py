from __future__ import annotations

from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from .repository import ArtifactIntegrityError
from .routes.all import router
from .services import APIValidationError, CKDAnalyticsService


def _error(code: str, message: str, details: dict[str, Any] | None = None) -> JSONResponse:
    return JSONResponse(
        status_code={
            "validation_error": 422,
            "not_found": 404,
            "method_not_allowed": 405,
            "artifact_integrity_error": 503,
            "invalid_request": 422,
        }.get(code, 500),
        content={"code": code, "message": message, "details": details or {}},
    )


def create_app(service: CKDAnalyticsService | None = None) -> FastAPI:
    app = FastAPI(title="CKD Launch Intelligence API", version="1.0.0", openapi_url="/openapi.json")
    app.state.service = service or CKDAnalyticsService()
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        return _error(
            "validation_error",
            "Request validation failed.",
            {
                "errors": [
                    {
                        "loc": list(error.get("loc", ())),
                        "type": error.get("type", "validation_error"),
                    }
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(APIValidationError)
    async def api_validation_handler(_: Request, exc: APIValidationError) -> JSONResponse:
        return _error(exc.code, str(exc))

    @app.exception_handler(ArtifactIntegrityError)
    async def integrity_handler(_: Request, __: ArtifactIntegrityError) -> JSONResponse:
        return _error(
            "artifact_integrity_error",
            "A committed analytics artifact failed integrity verification.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = (
            "method_not_allowed"
            if exc.status_code == 405
            else "not_found"
            if exc.status_code == 404
            else "http_error"
        )
        return _error(code, "The requested API operation is unavailable.")

    @app.exception_handler(Exception)
    async def unexpected_handler(_: Request, __: Exception) -> JSONResponse:
        return _error("internal_error", "The API could not complete the request.")

    return app


app = create_app()
