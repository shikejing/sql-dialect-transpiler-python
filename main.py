"""对外调用入口：FastAPI 暴露转译、往返校验与方言查询接口。"""

import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from transpiler import Transpiler, TranspileError, default_registry

app = FastAPI(title="SQL Dialect Transpiler")
transpiler = Transpiler()


class TranspileRequest(BaseModel):
    sql: str
    source: str
    target: str
    validate_roundtrip: bool = False  # 为 true 时执行往返语义校验


@app.get("/dialects")
def list_dialects():
    return [{"name": d.name, "version": d.version}
            for d in transpiler.registry.all()]


@app.post("/transpile")
def transpile(req: TranspileRequest):
    try:
        if req.validate_roundtrip:
            report = transpiler.validate_roundtrip(req.sql, req.source, req.target)
            if not report.ok:
                raise HTTPException(
                    status_code=422,
                    detail={"category": "roundtrip_mismatch", "diffs": list(report.diffs)})
            result = transpiler.transpile(req.sql, req.source, req.target)
            return {"sql": result.sql, "roundtrip_sql": report.roundtrip_sql,
                    "from_cache": result.from_cache}
        result = transpiler.transpile(req.sql, req.source, req.target)
        return {"sql": result.sql, "from_cache": result.from_cache}
    except TranspileError as e:
        # 语法错误 / 未知方言 / 不支持特性 三类错误分别映射状态码
        status = {"syntax_error": 400, "unknown_dialect": 404,
                  "unsupported_feature": 422}.get(e.category, 400)
        raise HTTPException(status_code=status,
                            detail={"category": e.category, "message": str(e)})


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=0)
