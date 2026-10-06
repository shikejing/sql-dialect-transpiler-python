"""缓存与并发：键覆盖方言组合与规则版本，规则更新后旧结果失效。"""

import threading
from dataclasses import replace

import pytest

from transpiler import DialectRegistry, Transpiler, default_registry
from transpiler.dialects import BUILTIN_DIALECTS, MYSQL


@pytest.fixture()
def t():
    return Transpiler()


def test_cache_hit_on_repeat(t):
    sql = "SELECT a FROM t LIMIT 5"
    r1 = t.transpile(sql, "mysql", "postgres")
    r2 = t.transpile(sql, "mysql", "postgres")
    assert not r1.from_cache and r2.from_cache
    assert r1.sql == r2.sql
    stats = t.cache_stats()
    assert stats["hits"] == 1 and stats["misses"] == 1


def test_cache_key_covers_dialect_pair(t):
    sql = "SELECT a FROM t LIMIT 5"
    t.transpile(sql, "mysql", "postgres")
    r = t.transpile(sql, "mysql", "mssql")  # 不同目标方言不得命中
    assert not r.from_cache
    r2 = t.transpile(sql, "postgres", "mysql")  # 不同源方言不得命中
    assert not r2.from_cache


def test_cache_invalidated_by_rule_version_bump():
    reg = default_registry()
    tp = Transpiler(reg)
    sql = "SELECT LENGTH(name) FROM t"
    before = tp.transpile(sql, "mysql", "mssql").sql
    assert before == "SELECT LEN(name) FROM t"

    # 规则升级：mssql 2.0.0 中 LENGTH 不再改名（示意规则变化）
    mssql_v2 = None
    for d in BUILTIN_DIALECTS:
        if d.name == "mssql":
            rules = dict(d.function_rules)
            del rules["LENGTH"]
            mssql_v2 = replace(d, version="2.0.0", function_rules=rules)
    reg.register(mssql_v2)

    after = tp.transpile(sql, "mysql", "mssql")
    assert not after.from_cache  # 旧缓存不得生效
    assert after.sql == "SELECT LENGTH(name) FROM t"
    # 源方言版本未变，mysql->postgres 的旧缓存仍然有效
    tp.transpile("SELECT a FROM t LIMIT 5", "mysql", "postgres")
    assert tp.transpile("SELECT a FROM t LIMIT 5", "mysql", "postgres").from_cache


def test_concurrent_transpile_consistent(t):
    sqls = [
        "SELECT a FROM t WHERE b = ? LIMIT 10",
        "SELECT name || 'x' FROM u",
        "SELECT IF(c > 1, 2, 3) FROM v",
        "SELECT created_at + INTERVAL 1 DAY FROM w",
    ]
    pairs = [("mysql", "postgres"), ("postgres", "mssql"),
             ("sqlite", "mysql"), ("mssql", "sqlite")]
    results, errors = {}, []

    def worker(n):
        try:
            for i in range(50):
                sql = sqls[(n + i) % len(sqls)]
                s, d = pairs[(n + i) % len(pairs)]
                results.setdefault((sql, s, d), set()).add(
                    t.transpile(sql, s, d).sql)
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    assert not errors
    # 同一输入在并发下结果唯一
    for key, outs in results.items():
        assert len(outs) == 1, f"inconsistent result for {key}: {outs}"


def test_registration_order_independence():
    reg1 = DialectRegistry()
    reg2 = DialectRegistry()
    for d in BUILTIN_DIALECTS:
        reg1.register(d)
    for d in reversed(BUILTIN_DIALECTS):
        reg2.register(d)
    t1, t2 = Transpiler(reg1), Transpiler(reg2)
    sql = "SELECT IF(a > 1, 'x', 'y') AS r, LENGTH(b) FROM t WHERE c = ? LIMIT 3 OFFSET 1"
    for s, d in [("mysql", "postgres"), ("mssql", "sqlite"), ("sqlite", "mssql")]:
        assert t1.transpile(sql, s, d).sql == t2.transpile(sql, s, d).sql


def test_conflicting_registration_rejected():
    reg = default_registry()
    with pytest.raises(ValueError, match="different rules"):
        reg.register(replace(MYSQL, native_boolean=True))  # 同名同版本不同规则
    reg.register(MYSQL)  # 完全相同的重复注册是幂等的
    reg.register(replace(MYSQL, version="1.1.0"))  # 同名新版本视为升级
    assert reg.get("mysql").version == "1.1.0"
