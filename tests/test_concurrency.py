"""并发转译：多线程共享一个 Transpiler，结果一致且无异常。"""
from concurrent.futures import ThreadPoolExecutor


def test_concurrent_transpile(tp):
    sqls = [
        "SELECT a FROM t WHERE x = ? LIMIT 5",
        "SELECT a || b FROM t WHERE f = TRUE",
        "SELECT DATE_ADD(d, INTERVAL 1 DAY) FROM t",
    ]
    pairs = [("mysql", "postgres"), ("postgres", "sqlserver"),
             ("sqlite", "mysql"), ("mysql", "sqlite")]

    def work(i):
        sql = sqls[i % len(sqls)]
        src, tgt = pairs[i % len(pairs)]
        return tp.transpile(sql, src, tgt).sql

    with ThreadPoolExecutor(max_workers=8) as ex:
        results = list(ex.map(work, range(200)))
    # 相同输入的输出必须一致
    def key(i):
        return (sqls[i % len(sqls)], pairs[i % len(pairs)])
    seen = {}
    for i, out in enumerate(results):
        assert seen.setdefault(key(i), out) == out
