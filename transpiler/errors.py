"""错误分类体系：解析错误 / 未知方言 / 目标方言不支持的特性。"""
from __future__ import annotations

from enum import Enum


class ErrorKind(Enum):
    PARSE = "parse"
    UNKNOWN_DIALECT = "unknown_dialect"
    UNSUPPORTED_FEATURE = "unsupported_feature"


class TranspileError(Exception):
    """所有转译错误的基类，携带分类、位置与可读原因。"""

    kind: ErrorKind

    def __init__(self, message: str, *, position: int | None = None,
                 detail: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.position = position
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "kind": self.kind.value,
            "message": self.message,
            "position": self.position,
            "detail": self.detail,
        }


class SqlParseError(TranspileError):
    kind = ErrorKind.PARSE


class UnknownDialectError(TranspileError):
    kind = ErrorKind.UNKNOWN_DIALECT


class UnsupportedFeatureError(TranspileError):
    kind = ErrorKind.UNSUPPORTED_FEATURE
