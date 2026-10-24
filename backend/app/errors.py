"""Consistent error responses:  {"error": {"code": ..., "message": ..., "details": ...}}

MySQL errors are translated so clients never see SQL text, credentials or stack traces.
"""
import logging

import pymysql
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("erm")


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, details=None):
        self.status, self.code, self.message, self.details = status, code, message, details


def not_found(what: str) -> ApiError:
    return ApiError(404, "NOT_FOUND", f"{what} not found")


def forbidden(message: str = "You do not have permission to perform this action") -> ApiError:
    return ApiError(403, "FORBIDDEN", message)


def _body(code: str, message: str, details=None) -> dict:
    error = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"error": error}


# MySQL error number -> (HTTP status, code, safe message or None to use MySQL's text)
_MYSQL_ERRORS = {
    31400: (400, "VALIDATION_ERROR", None),         # SIGNAL from procedures/triggers
    31404: (404, "NOT_FOUND", None),
    31409: (409, "BUSINESS_RULE_VIOLATION", None),
    1062: (409, "DUPLICATE", "A record with the same unique value already exists"),
    1452: (400, "INVALID_REFERENCE", "A referenced record does not exist"),
    1216: (400, "INVALID_REFERENCE", "A referenced record does not exist"),
    1217: (409, "IN_USE", "Record is referenced by other records and cannot be deleted"),
    1451: (409, "IN_USE", "Record is referenced by other records and cannot be deleted"),
    3819: (400, "CONSTRAINT_VIOLATION", "Value violates a database constraint"),
    1048: (400, "VALIDATION_ERROR", "A required value is missing"),
    1406: (400, "VALIDATION_ERROR", "A value is too long"),
    1142: (403, "DB_PERMISSION_DENIED", "Database privileges do not allow this operation for your role"),
    1143: (403, "DB_PERMISSION_DENIED", "Database privileges do not allow this operation for your role"),
    1370: (403, "DB_PERMISSION_DENIED", "Database privileges do not allow this operation for your role"),
}


def mysql_error_response(exc: pymysql.MySQLError) -> JSONResponse:
    errno = exc.args[0] if exc.args and isinstance(exc.args[0], int) else None
    if errno in _MYSQL_ERRORS:
        status, code, message = _MYSQL_ERRORS[errno]
        if errno == 3819 and len(exc.args) > 1:
            # constraint names are part of the documented schema, safe to expose
            message = f"Value violates database constraint: {str(exc.args[1]).split(chr(39))[1]}"
        return JSONResponse(status_code=status, content=_body(code, message or str(exc.args[1])))
    if isinstance(exc, pymysql.OperationalError) and errno in (2003, 2006, 2013, 1045):
        log.error("Database unavailable: errno=%s", errno)
        return JSONResponse(status_code=503, content=_body("DATABASE_UNAVAILABLE", "Database is unavailable"))
    log.exception("Unhandled MySQL error errno=%s", errno)
    return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "Internal server error"))


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(ApiError)
    async def _api_error(_: Request, exc: ApiError):
        return JSONResponse(status_code=exc.status, content=_body(exc.code, exc.message, exc.details))

    @app.exception_handler(pymysql.MySQLError)
    async def _mysql_error(_: Request, exc: pymysql.MySQLError):
        return mysql_error_response(exc)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(_: Request, exc: RequestValidationError):
        details = [
            {"field": ".".join(str(p) for p in e["loc"] if p != "body"), "message": e["msg"]}
            for e in exc.errors()
        ]
        return JSONResponse(status_code=422, content=_body("VALIDATION_ERROR", "Invalid request", details))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(_: Request, exc: StarletteHTTPException):
        code = {401: "UNAUTHORIZED", 403: "FORBIDDEN", 404: "NOT_FOUND", 405: "METHOD_NOT_ALLOWED"}.get(
            exc.status_code, "HTTP_ERROR")
        return JSONResponse(status_code=exc.status_code, content=_body(code, str(exc.detail)),
                            headers=getattr(exc, "headers", None))

    @app.exception_handler(Exception)
    async def _unhandled(_: Request, exc: Exception):
        log.exception("Unhandled error")
        return JSONResponse(status_code=500, content=_body("INTERNAL_ERROR", "Internal server error"))
