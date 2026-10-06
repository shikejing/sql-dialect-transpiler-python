"""往返语义校验：source -> target -> source 后关键结构对齐。"""

import pytest


@pytest.mark.parametrize("sql", [
    "SELECT a, b AS c FROM t WHERE x = ? AND y > 2 LIMIT 10 OFFSET 5",
    "SELECT a || b FROM t WHERE f = TRUE",
    "SELECT DATE_ADD(d, INTERVAL 3 DAY) FROM t",
    "SELECT UPPER(a), LENGTH(b) FROM t LIMIT 3",
])
@pytest.mark.parametrize("target", ["postgres", "sqlite", "sqlserver"])
def test_roundtrip_ok(tp, sql, target):
    report = tp.validate_roundtrip(sql, "mysql", target)
    assert report.ok, report.differences
    assert report.target_sql
    assert report.roundtrip_sql


def test_roundtrip_report_fields(tp):
    report = tp.validate_roundtrip("SELECT a FROM t LIMIT 1", "mysql", "postgres")
    assert report.ok
    assert report.differences == []
    assert "LIMIT 1" in report.roundtrip_sql
