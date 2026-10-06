"""FastAPI 对外调用入口。"""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .builtins import register_builtins
from .dialects import list_dialects
from .engine import Transpiler
from .errors import ErrorKind, TranspileError


class TranspileRequest(BaseModel):
    sql: str
    source: str
    target: str


class ValidateRequest(BaseModel):
    sql: str
    source: str
    target: str


_STATUS = {
    ErrorKind.PARSE: 422,
    ErrorKind.UNKNOWN_DIALECT: 400,
    ErrorKind.UNSUPPORTED_FEATURE: 422,
}


def create_app(transpiler: Transpiler | None = None) -> FastAPI:
    register_builtins()
    tp = transpiler or Transpiler()
    app = FastAPI(title="SQL Dialect Transpiler")

    @app.exception_handler(TranspileError)
    async def _transpile_error(request, exc: TranspileError):
        return JSONResponse(status_code=_STATUS[exc.kind],
                            content={"error": exc.to_dict()})

    @app.post("/transpile")
    def transpile(req: TranspileRequest):
        result = tp.transpile(req.sql, req.source, req.target)
        return {"sql": result.sql, "source": result.source,
                "target": result.target, "cached": result.cached}

    @app.post("/validate")
    def validate(req: ValidateRequest):
        report = tp.validate_roundtrip(req.sql, req.source, req.target)
        return {"ok": report.ok, "target_sql": report.target_sql,
                "roundtrip_sql": report.roundtrip_sql,
                "differences": report.differences}

    @app.get("/dialects")
    def dialects():
        return {"dialects": [
            {"name": d.name, "version": d.version,
             "placeholder_style": d.placeholder_style,
             "pagination_style": d.pagination_style}
            for d in list_dialects()]}

    return app
