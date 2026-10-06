"""HTTP 入口：转译、往返校验、方言列表、错误分类状态码。"""
import pytest
from fastapi.testclient import TestClient

from transpiler.api import create_app


@pytest.fixture()
def client():
    return TestClient(create_app())


def test_transpile_endpoint(client):
    r = client.post("/transpile", json={
        "sql": "SELECT a FROM t WHERE x = ? LIMIT 5",
        "source": "sqlite", "target": "postgres"})
    assert r.status_code == 200
    body = r.json()
    assert body["sql"] == 'SELECT "a" FROM "t" WHERE "x" = $1 LIMIT 5'
    assert body["cached"] is False
    r2 = client.post("/transpile", json={
        "sql": "SELECT a FROM t WHERE x = ? LIMIT 5",
        "source": "sqlite", "target": "postgres"})
    assert r2.json()["cached"] is True


def test_validate_endpoint(client):
    r = client.post("/validate", json={
        "sql": "SELECT a || b FROM t", "source": "sqlite", "target": "mysql"})
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_dialects_endpoint(client):
    r = client.get("/dialects")
    names = {d["name"] for d in r.json()["dialects"]}
    assert names == {"mysql", "postgres", "sqlite", "sqlserver"}
    assert all(d["version"] for d in r.json()["dialects"])


def test_error_classification(client):
    r = client.post("/transpile", json={
        "sql": "SELECT a FROM", "source": "mysql", "target": "postgres"})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "parse"
    assert r.json()["error"]["position"] is not None

    r = client.post("/transpile", json={
        "sql": "SELECT 1", "source": "db2", "target": "mysql"})
    assert r.status_code == 400
    assert r.json()["error"]["kind"] == "unknown_dialect"

    r = client.post("/transpile", json={
        "sql": "SELECT NOW()", "source": "mysql", "target": "sqlite"})
    assert r.status_code == 422
    assert r.json()["error"]["kind"] == "unsupported_feature"
