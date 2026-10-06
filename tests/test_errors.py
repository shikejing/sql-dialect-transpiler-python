"""错误分类：解析错误 / 未知方言 / 不支持的特性。"""
import pytest

from transpiler.errors import (ErrorKind, SqlParseError, TranspileError,
                               UnknownDialectError, UnsupportedFeatureError)


def test_parse_error_has_position(tp):
    with pytest.raises(SqlParseError) as ei:
        tp.transpile("SELECT a FROM", "mysql", "postgres")
    assert ei.value.kind == ErrorKind.PARSE
    assert ei.value.position is not None


def test_parse_error_unclosed_string(tp):
    with pytest.raises(SqlParseError):
        tp.transpile("SELECT 'abc FROM t", "mysql", "postgres")


def test_unknown_dialect(tp):
    with pytest.raises(UnknownDialectError) as ei:
        tp.transpile("SELECT 1", "oracle", "mysql")
    assert ei.value.kind == ErrorKind.UNKNOWN_DIALECT
    assert "oracle" in ei.value.message


def test_unsupported_feature(tp):
    with pytest.raises(UnsupportedFeatureError) as ei:
        tp.transpile("SELECT NOW()", "mysql", "sqlite")
    assert ei.value.kind == ErrorKind.UNSUPPORTED_FEATURE
    assert "now" in ei.value.message


def test_negative_limit_rejected(tp):
    with pytest.raises(TranspileError):
        tp.transpile("SELECT a FROM t LIMIT -1", "mysql", "postgres")


def test_dynamic_interval_sqlite_rejected(tp):
    with pytest.raises(UnsupportedFeatureError):
        tp.transpile("SELECT DATE_ADD(d, INTERVAL ? DAY) FROM t",
                     "mysql", "sqlite")


def test_error_to_dict(tp):
    try:
        tp.transpile("SELECT a FROM", "mysql", "postgres")
    except TranspileError as e:
        d = e.to_dict()
        assert set(d) == {"kind", "message", "position", "detail"}
