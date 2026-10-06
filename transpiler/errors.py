"""错误类型定义：区分语法错误、未知方言、目标方言不支持特性三类情况。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class TranspileError(Exception):
    """所有转译错误的基类。调用方只需捕获此类型即可。"""

    category: str = "transpile_error"

    def __init__(self, message: str, *, position: Optional[int] = None,
                 reason: Optional[str] = None):
        self.message = message
        self.position = position
        self.reason = reason
        super().__init__(self.__str__())

    def __str__(self) -> str:
        out = f"[{self.category}] {self.message}"
        details = []
        if self.position is not None:
            details.append(f"at position {self.position}")
        if self.reason:
            details.append(f"reason: {self.reason}")
        if details:
            out += " (" + ", ".join(details) + ")"
        return out


class SqlSyntaxError(TranspileError):
    """输入 SQL 存在语法错误。position 指向出错字符偏移。"""

    category = "syntax_error"


class UnknownDialectError(TranspileError):
    """引用了未注册的方言。"""

    category = "unknown_dialect"

    def __init__(self, dialect: str, *, available: Optional[list[str]] = None):
        self.dialect = dialect
        self.available = sorted(available) if available else []
        msg = f"unknown dialect: {dialect!r}"
        if self.available:
            msg += f"; available: {', '.join(self.available)}"
        super().__init__(msg)


class UnsupportedFeatureError(TranspileError):
    """目标方言不支持某特性，且无法给出语义等价的改写。"""

    category = "unsupported_feature"

    def __init__(self, feature: str, *, source: str, target: str,
                 reason: Optional[str] = None, position: Optional[int] = None):
        self.feature = feature
        self.source = source
        self.target = target
        super().__init__(
            f"feature {feature!r} is not supported when transpiling "
            f"{source} -> {target}",
            position=position,
            reason=reason,
        )


class RoundtripMismatchError(TranspileError):
    """往返校验失败：转回源方言后关键结构无法对齐。"""

    category = "roundtrip_mismatch"

    def __init__(self, diffs: list[str]):
        self.diffs = list(diffs)
        super().__init__("roundtrip validation failed: " + "; ".join(self.diffs))
