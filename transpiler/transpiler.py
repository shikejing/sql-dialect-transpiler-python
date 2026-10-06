"""转译核心。

流程：parse -> normalize（源侧函数名归一）-> generate（目标方言规则）。
提供线程安全的结果缓存与往返语义校验。核心只依赖 Dialect 规则记录，
新增方言无需改动本模块。
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from dataclasses import dataclass, fields, is_dataclass
from typing import Dict, List, Optional, Tuple

from .ast_nodes import (
    BinaryOp, BooleanLiteral, CaseExpr, Column, Expr, FuncCall, Identifier,
    Interval, NumberLiteral, Placeholder, Select, SelectItem, OrderItem,
)
from .dialects import CANONICAL_ALIASES, Dialect
from .errors import RoundtripMismatchError, TranspileError
from .generator import Generator
from .parser import parse
from .registry import DialectRegistry, default_registry


# ---------------------------------------------------------------------------
# 源侧归一：方言专有函数写法 -> 规范形式
# ---------------------------------------------------------------------------

def normalize_expr(expr: Expr) -> Expr:
    if isinstance(expr, FuncCall):
        args = tuple(normalize_expr(a) for a in expr.args)
        name = CANONICAL_ALIASES.get(expr.name, expr.name)
        if name == "CURRENT_TIMESTAMP":
            return FuncCall(name, ())
        if expr.name == "CONCAT" and len(args) >= 2:
            # CONCAT(a, b, ...) 与 a || b || ... 统一为二元 CONCAT 链
            acc: Expr = args[0]
            for a in args[1:]:
                acc = BinaryOp("CONCAT", acc, a)
            return acc
        if expr.name in ("DATE_ADD", "DATE_SUB") and len(args) == 2 \
                and isinstance(args[1], Interval):
            # 函数形式的日期运算与 + INTERVAL 统一
            return BinaryOp(expr.name, args[0], args[1])
        if expr.name == "IF" and len(args) == 3:
            # mysql 专有 IF(c, a, b) 归一为标准 CASE 表达式
            return CaseExpr(((args[0], args[1]),), args[2])
        if expr.name == "DATEADD" and len(args) == 3:
            # mssql DATEADD(unit, n, expr) -> DATE_ADD(expr, INTERVAL n unit)
            unit_arg = args[0]
            if isinstance(unit_arg, Column) and unit_arg.table is None:
                return BinaryOp("DATE_ADD", normalize_expr(args[2]),
                                Interval(args[1], unit_arg.name.name.upper()))
        return FuncCall(name, args)
    if isinstance(expr, BinaryOp):
        return BinaryOp(expr.op, normalize_expr(expr.left), normalize_expr(expr.right))
    if isinstance(expr, CaseExpr):
        return CaseExpr(
            tuple((normalize_expr(c), normalize_expr(v)) for c, v in expr.whens),
            normalize_expr(expr.else_) if expr.else_ is not None else None,
        )
    if isinstance(expr, Interval):
        return Interval(normalize_expr(expr.value), expr.unit)
    return expr


def normalize_statement(stmt: Select) -> Select:
    return Select(
        columns=tuple(SelectItem(normalize_expr(c.expr), c.alias) for c in stmt.columns),
        from_table=stmt.from_table,
        where=normalize_expr(stmt.where) if stmt.where is not None else None,
        order_by=stmt.order_by,
        limit=stmt.limit,
        offset=stmt.offset,
    )


# ---------------------------------------------------------------------------
# 往返结构对比
# ---------------------------------------------------------------------------

def _bool_equiv(a: Expr, b: Expr) -> bool:
    """无原生布尔字面量的方言中 TRUE/FALSE 与 1/0 语义等价。"""
    def as_bool(e: Expr) -> Optional[bool]:
        if isinstance(e, BooleanLiteral):
            return e.value
        if isinstance(e, NumberLiteral) and e.value in ("1", "0"):
            return e.value == "1"
        return None
    x, y = as_bool(a), as_bool(b)
    return x is not None and x == y


def _number_equiv(a: Expr, b: Expr) -> bool:
    if isinstance(a, NumberLiteral) and isinstance(b, NumberLiteral):
        try:
            return float(a.value) == float(b.value)
        except ValueError:
            return a.value == b.value
    return False


def diff_expr(a: Expr, b: Expr, path: str, diffs: List[str]) -> None:
    """递归对比两个表达式，把不可对齐的差异以可读形式记录到 diffs。"""
    if type(a) is not type(b):
        if _bool_equiv(a, b) or _number_equiv(a, b):
            return
        diffs.append(f"{path}: {a!r} != {b!r}")
        return
    if isinstance(a, Placeholder):
        # 命名占位符转位置占位符后名字可能丢失，按出现位置对齐即可
        if a.index != b.index:
            diffs.append(f"{path}: placeholder #{a.index} != #{b.index}")
        return
    if isinstance(a, Identifier):
        if a.name != b.name:
            diffs.append(f"{path}: identifier {a.name!r} != {b.name!r}")
        return
    if isinstance(a, FuncCall) and a.name != b.name:
        diffs.append(f"{path}: function {a.name} != {b.name}")
        return
    if isinstance(a, (BinaryOp,)) and a.op != b.op:
        # mssql 字符串拼接与算术加法共用 +，往返后运算符可能无法区分
        if {a.op, b.op} == {"CONCAT", "+"}:
            pass
        else:
            diffs.append(f"{path}: operator {a.op} != {b.op}")
            return
    if isinstance(a, Interval) and a.unit != b.unit:
        diffs.append(f"{path}: interval unit {a.unit} != {b.unit}")
        return
    handled = set()
    if isinstance(a, BinaryOp):
        handled.add("op")
    if isinstance(a, FuncCall):
        handled.add("name")
    if isinstance(a, Interval):
        handled.add("unit")
    for f in fields(a):
        if f.name in handled:
            continue
        va, vb = getattr(a, f.name), getattr(b, f.name)
        _diff_value(va, vb, f"{path}.{f.name}", diffs)


def _diff_value(va, vb, path: str, diffs: List[str]) -> None:
    if isinstance(va, Expr) and isinstance(vb, Expr):
        diff_expr(va, vb, path, diffs)
    elif isinstance(va, tuple) and isinstance(vb, tuple):
        if len(va) != len(vb):
            diffs.append(f"{path}: length {len(va)} != {len(vb)}")
            return
        for i, (xa, xb) in enumerate(zip(va, vb)):
            _diff_value(xa, xb, f"{path}[{i}]", diffs)
    elif is_dataclass(va) and is_dataclass(vb):
        for f in fields(va):
            _diff_value(getattr(va, f.name), getattr(vb, f.name),
                        f"{path}.{f.name}", diffs)
    elif va != vb:
        diffs.append(f"{path}: {va!r} != {vb!r}")


def diff_statement(a: Select, b: Select) -> List[str]:
    diffs: List[str] = []
    _diff_value(a, b, "select", diffs)
    return diffs


# ---------------------------------------------------------------------------
# 转译器
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class TranspileResult:
    sql: str
    source: str
    target: str
    source_version: str
    target_version: str
    from_cache: bool = False


@dataclass(frozen=True)
class RoundtripReport:
    source_sql: str
    target_sql: str
    roundtrip_sql: str
    diffs: Tuple[str, ...]

    @property
    def ok(self) -> bool:
        return not self.diffs


class Transpiler:
    """线程安全；缓存键覆盖 SQL 文本与双方言 (名称, 版本)，
    规则升级后旧缓存自然失效。"""

    def __init__(self, registry: Optional[DialectRegistry] = None,
                 cache_size: int = 1024):
        self.registry = registry or default_registry()
        self._cache_size = cache_size
        self._cache: "OrderedDict[tuple, str]" = OrderedDict()
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    # ------------------------------------------------------------------

    def transpile(self, sql: str, source: str, target: str) -> TranspileResult:
        src = self.registry.get(source)
        dst = self.registry.get(target)
        key = (sql, src.cache_key(), dst.cache_key())
        with self._lock:
            cached = self._cache.get(key)
            if cached is not None:
                self._cache.move_to_end(key)
                self.hits += 1
                return TranspileResult(cached, src.name, dst.name,
                                       src.version, dst.version, from_cache=True)
            self.misses += 1
        out = self._do_transpile(sql, src, dst)
        with self._lock:
            self._cache[key] = out
            self._cache.move_to_end(key)
            while len(self._cache) > self._cache_size:
                self._cache.popitem(last=False)
        return TranspileResult(out, src.name, dst.name, src.version, dst.version)

    def _do_transpile(self, sql: str, src: Dialect, dst: Dialect) -> str:
        stmt = normalize_statement(parse(sql))
        return Generator(dst, source_name=src.name).render(stmt)

    # ------------------------------------------------------------------
    # 往返校验
    # ------------------------------------------------------------------

    def validate_roundtrip(self, sql: str, source: str, target: str) -> RoundtripReport:
        """转到目标方言再转回，对比关键结构；差异以可读形式返回。"""
        forward = self.transpile(sql, source, target)
        back = self.transpile(forward.sql, target, source)
        original = normalize_statement(parse(sql))
        roundtripped = normalize_statement(parse(back.sql))
        diffs = tuple(diff_statement(original, roundtripped))
        return RoundtripReport(sql, forward.sql, back.sql, diffs)

    def transpile_checked(self, sql: str, source: str, target: str) -> TranspileResult:
        """转译并做往返校验，结构无法对齐时抛出 RoundtripMismatchError。"""
        report = self.validate_roundtrip(sql, source, target)
        if not report.ok:
            raise RoundtripMismatchError(list(report.diffs))
        return self.transpile(sql, source, target)

    # ------------------------------------------------------------------

    def cache_stats(self) -> Dict[str, int]:
        with self._lock:
            return {"size": len(self._cache), "hits": self.hits, "misses": self.misses}

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()
            self.hits = 0
            self.misses = 0
