"""错误分类：语法错误 / 未知方言 / 不支持特性，带位置与原因。"""

import pytest

from transpiler import Transpiler
from transpiler.errors import (
    SqlSyntaxError, TranspileError, UnknownDialectError, UnsupportedFeatureError,
)


@pytest.fixture(scope="module")
def t():
    return Transpiler()


def test_syntax_error_has_position(t):
    with pytest.raises(SqlSyntaxError) as exc:
        t.transpile("SELECT a FROM WHERE x = 1", "mysql", "postgres")
    assert exc.value.category == "syntax_error"
    assert exc.value.position == 14  # WHERE 关键字位置
    assert "WHERE" in str(exc.value)


def test_syntax_error_unterminated_string(t):
    with pytest.raises(SqlSyntaxError) as exc:
        t.transpile("SELECT 'abc FROM t", "mysql", "postgres")
    assert exc.value.position == 7
    assert "unterminated string" in str(exc.value)


def test_syntax_error_trailing_input(t):
    with pytest.raises(SqlSyntaxError, match="unexpected trailing input"):
        t.transpile("SELECT a FROM t SELECT", "mysql", "postgres")


def test_unknown_dialect_lists_available(t):
    with pytest.raises(UnknownDialectError) as exc:
        t.transpile("SELECT 1", "oracle", "mysql")
    assert exc.value.category == "unknown_dialect"
    assert "oracle" in str(exc.value)
    assert "mysql" in str(exc.value)  # 可用方言列表
    with pytest.raises(UnknownDialectError):
        t.transpile("SELECT 1", "mysql", "db2")


def test_unsupported_feature_reports_reason(t):
    with pytest.raises(UnsupportedFeatureError) as exc:
        t.transpile("SELECT ARRAY_AGG(x) FROM t", "postgres", "mysql")
    e = exc.value
    assert e.category == "unsupported_feature"
    assert e.source == "postgres" and e.target == "mysql"
    assert "ARRAY_AGG" in str(e) and "array" in e.reason


def test_unsupported_regexp_replace(t):
    with pytest.raises(UnsupportedFeatureError, match="REGEXP_REPLACE"):
        t.transpile("SELECT REGEXP_REPLACE(a, 'x', 'y') FROM t", "postgres", "sqlite")
    # 但 postgres -> mysql 有等价实现，不应报错
    out = Transpiler().transpile("SELECT REGEXP_REPLACE(a, 'x', 'y') FROM t",
                                 "postgres", "mysql").sql
    assert "REGEXP_REPLACE" in out


def test_all_errors_share_base_class(t):
    for sql, src, dst in [("SELECT FROM", "mysql", "postgres"),
                          ("SELECT 1", "nope", "mysql"),
                          ("SELECT ARRAY_AGG(x) FROM t", "postgres", "mysql")]:
        with pytest.raises(TranspileError):
            t.transpile(sql, src, dst)


def test_error_message_hides_parser_internals(t):
    # 报错信息不含解析器内部实现细节（如模块名、堆栈帧）
    try:
        t.transpile("SELECT a FROM t WHERE = 1", "mysql", "postgres")
    except SqlSyntaxError as e:
        msg = str(e)
        assert "parser" not in msg and "tokenize" not in msg
        assert "unexpected token '='" in msg
