"""跨方言 SQL 转译包。对外入口：Transpiler / transpile / register_dialect。"""
from .dialects import DialectRules, get_dialect, list_dialects, register_dialect
from .engine import RoundTripReport, Transpiler, TranspileResult
from .errors import (ErrorKind, SqlParseError, TranspileError,
                     UnknownDialectError, UnsupportedFeatureError)

__all__ = [
    "DialectRules", "get_dialect", "list_dialects", "register_dialect",
    "Transpiler", "TranspileResult", "RoundTripReport",
    "TranspileError", "SqlParseError", "UnknownDialectError",
    "UnsupportedFeatureError", "ErrorKind",
]
