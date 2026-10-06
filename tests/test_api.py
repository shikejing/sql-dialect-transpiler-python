"""对外 HTTP 入口：转译、方言列表、错误状态码映射。"""

import pytest
from fastapi.testclient import TestClient

from main import app

client = TestClient(app)


def test_list_dialects():
    resp = client.get("/dialects")
    assert resp.status_code == 200
    names = {d["name"] for d in resp.json()}
    assert names == {"mysql", "postgres", "sqlite", "mssql"}
    assert all(d["version"] for d in resp.json())


def test_transpile_endpoint():
    resp = client.post("/transpile", json={
        "sql": "SELECT name || 'x' FROM users WHERE id = ? LIMIT 10",
        "source": "postgres", "target": "mysql"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["sql"] == "SELECT CONCAT(name, 'x') FROM users WHERE id = ? LIMIT 10"
    assert body["from_cache"] is False
    # 第二次相同请求命中缓存
    resp2 = client.post("/transpile", json={
        "sql": "SELECT name || 'x' FROM users WHERE id = ? LIMIT 10",
        "source": "postgres", "target": "mysql"})
    assert resp2.json()["from_cache"] is True


def test_transpile_with_roundtrip_validation():
    resp = client.post("/transpile", json={
        "sql": "SELECT IF(a > 1, 2, 3) FROM t",
        "source": "mysql", "target": "postgres",
        "validate_roundtrip": True})
    assert resp.status_code == 200
    assert resp.json()["sql"] == "SELECT CASE WHEN a > 1 THEN 2 ELSE 3 END FROM t"
    assert "roundtrip_sql" in resp.json()


def test_error_status_mapping():
    # 语法错误 -> 400
    resp = client.post("/transpile", json={
        "sql": "SELECT FROM WHERE", "source": "mysql", "target": "postgres"})
    assert resp.status_code == 400
    assert resp.json()["detail"]["category"] == "syntax_error"
    # 未知方言 -> 404
    resp = client.post("/transpile", json={
        "sql": "SELECT 1", "source": "oracle", "target": "mysql"})
    assert resp.status_code == 404
    assert resp.json()["detail"]["category"] == "unknown_dialect"
    # 不支持特性 -> 422
    resp = client.post("/transpile", json={
        "sql": "SELECT ARRAY_AGG(x) FROM t", "source": "postgres", "target": "mysql"})
    assert resp.status_code == 422
    assert resp.json()["detail"]["category"] == "unsupported_feature"
