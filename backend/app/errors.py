"""Uniform error responses: { "error": { "code": "...", "message": "..." } }."""

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException


class ApiError(Exception):
    """Raise from routes or services to return a plain-language error."""

    def __init__(self, status: int, code: str, message: str):
        self.status = status
        self.code = code
        self.message = message


def _body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


_STATUS_CODES = {
    400: ("bad_request", "The request was not valid."),
    401: ("not_logged_in", "Please log in to continue."),
    403: ("forbidden", "You don't have access to this."),
    404: ("not_found", "That page or item doesn't exist."),
    405: ("method_not_allowed", "That action isn't allowed here."),
}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_req: Request, exc: ApiError) -> JSONResponse:
        return JSONResponse(_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_req: Request, exc: StarletteHTTPException) -> JSONResponse:
        code, message = _STATUS_CODES.get(exc.status_code, ("error", "Something went wrong."))
        return JSONResponse(_body(code, message), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_req: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        field = ".".join(str(p) for p in first.get("loc", [])[1:]) or "request"
        message = f"Check the {field} field: {first.get('msg', 'invalid value')}."
        return JSONResponse(_body("invalid_input", message), status_code=422)

    @app.exception_handler(Exception)
    async def _unexpected(_req: Request, _exc: Exception) -> JSONResponse:
        return JSONResponse(
            _body("server_error", "Something went wrong on the server. Please try again."),
            status_code=500,
        )
