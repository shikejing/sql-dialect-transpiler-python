"""往返语义校验：关键结构对齐，无法对齐时给出可读差异。"""

import pytest

from transpiler import (
    Dialect, DialectRegistry, FunctionRule, Transpiler, default_registry,
)
from transpiler.dialects import (
    CONCAT_OPERATOR, DATE_INTERVAL, PAGE_LIMIT_OFFSET, PH_QMARK, MYSQL,
)
from transpiler.errors import RoundtripMismatchError
from transpiler.transpiler import diff_statement
from transpiler.parser import parse


@pytest.fixture(scope="module")
def t():
    return Transpiler()


@pytest.mark.parametrize("sql,source,target", [
    ("SELECT a, b AS x FROM t WHERE c = ? AND d > 1 ORDER BY a DESC LIMIT 5 OFFSET 2",
     "mysql", "postgres"),
    ("SELECT name || 'x' FROM users WHERE active = TRUE", "postgres", "mysql"),
    ("SELECT IF(a > 1, 2, 3) FROM t", "mysql", "sqlite"),
    ("SELECT created_at + INTERVAL 1 DAY FROM t", "mysql", "postgres"),
    ("SELECT CASE WHEN a THEN 1 ELSE 0 END FROM t", "mysql", "mssql"),
    ("SELECT CONCAT(a, b) FROM t LIMIT 10", "mysql", "mssql"),
    ("SELECT COALESCE(a, 0), LENGTH(b) FROM t", "postgres", "sqlite"),
])
def test_roundtrip_ok(t, sql, source, target):
    report = t.validate_roundtrip(sql, source, target)
    assert report.ok, "\n".join(report.diffs)


def test_roundtrip_boolean_number_equiv(t):
    # mysql 无原生布尔，TRUE -> 1 -> TRUE 仍判定为对齐
    report = t.validate_roundtrip("SELECT * FROM t WHERE a = TRUE", "mysql", "postgres")
    assert report.ok


def test_transpile_checked_raises_on_mismatch():
    # 注册一个有损方言：LENGTH 被改写为无法对齐的表达式
    lossy = Dialect(
        name="lossy", version="1.0.0", quote_open='"', quote_close='"',
        placeholder=PH_QMARK, native_boolean=True,
        concat_style=CONCAT_OPERATOR, pagination=PAGE_LIMIT_OFFSET,
        date_arith=DATE_INTERVAL,
        function_rules={"LENGTH": FunctionRule.template("({0} || '')")},
    )
    reg = DialectRegistry()
    reg.register(MYSQL)
    reg.register(lossy)
    tp = Transpiler(reg)
    with pytest.raises(RoundtripMismatchError) as exc:
        tp.transpile_checked("SELECT LENGTH(a) FROM t", "mysql", "lossy")
    # 差异说明可读：指明路径与两侧结构
    assert any("columns" in d for d in exc.value.diffs)


def test_diff_statement_reports_readable_paths():
    a = parse("SELECT a FROM t WHERE x = 1")
    b = parse("SELECT a FROM t WHERE x = 2")
    diffs = diff_statement(a, b)
    assert len(diffs) == 1
    assert "where" in diffs[0] and "'1'" in diffs[0] and "'2'" in diffs[0]
