"""跨方言 SQL 转译器。

用法::

    from transpiler import Transpiler
    t = Transpiler()
    t.transpile("SELECT * FROM t LIMIT 10", source="mysql", target="postgres")
"""

from .dialects import BUILTIN_DIALECTS, Dialect, FunctionRule
from .errors import (
    RoundtripMismatchError, SqlSyntaxError, TranspileError,
    UnknownDialectError, UnsupportedFeatureError,
)
from .registry import DialectRegistry, default_registry
from .transpiler import RoundtripReport, TranspileResult, Transpiler

__all__ = [
    "BUILTIN_DIALECTS",
    "Dialect",
    "DialectRegistry",
    "FunctionRule",
    "RoundtripMismatchError",
    "RoundtripReport",
    "SqlSyntaxError",
    "TranspileError",
    "TranspileResult",
    "Transpiler",
    "UnknownDialectError",
    "UnsupportedFeatureError",
    "default_registry",
]
