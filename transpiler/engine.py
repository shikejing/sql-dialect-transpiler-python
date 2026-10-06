"""转译引擎：组合解析/规范化/生成，提供并发安全缓存与往返语义校验。"""
from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field

from . import ast_nodes as A
from .ast_nodes import Select
from .dialects import DialectRules, get_dialect, registry_generation
from .generator import generate
from .parser import parse


@dataclass
class TranspileResult:
    sql: str
    source: str
    target: str
    cached: bool = False


@dataclass
class RoundTripReport:
    ok: bool
    source_sql: str = ""
    target_sql: str = ""
    roundtrip_sql: str = ""
    differences: list[str] = field(default_factory=list)


# ---------- 规范化 ----------

def _fold(name: str, rules: DialectRules) -> str:
    if rules.fold_unquoted == "lower":
        return name.lower()
    if rules.fold_unquoted == "upper":
        return name.upper()
    return name


def normalize(stmt: Select, source_rules: DialectRules) -> Select:
    """按源方言规则折叠未加引号标识符的大小写，保证书写风格不影响结果。"""
    def walk(node):
        if isinstance(node, A.Identifier):
            if not node.quoted:
                node.name = _fold(node.name, source_rules)
            return node
        if isinstance(node, A.QualifiedName):
            if not node.quoted:
                node.parts = [_fold(p, source_rules) for p in node.parts]
            return node
        for f in vars(node).values():
            if isinstance(f, A.Node):
                walk(f)
            elif isinstance(f, list):
                for item in f:
                    if isinstance(item, A.Node):
                        walk(item)
        return node

    walk(stmt)
    for item in stmt.items:
        if item.alias:
            item.alias = _fold(item.alias, source_rules)
    return stmt


# ---------- 结构规范化表示（往返对齐用） ----------

def canonical_key(stmt) -> tuple:
    """生成 AST 的规范化结构表示，忽略标识符是否带引号等表面差异。"""
    def key(node):
        if node is None:
            return None
        if isinstance(node, A.Identifier):
            return ("ident", node.name)
        if isinstance(node, A.QualifiedName):
            return ("qname", tuple(node.parts))
        if isinstance(node, A.Literal):
            return ("lit", node.kind, node.value)
        if isinstance(node, A.BooleanLiteral):
            # 无布尔字面量的方言会退化为 1/0，对齐时视为等价
            return ("lit", "number", 1 if node.value else 0)
        if isinstance(node, A.Placeholder):
            return ("ph", node.index)
        if isinstance(node, A.BinaryOp):
            return ("binop", node.op, key(node.left), key(node.right))
        if isinstance(node, A.UnaryOp):
            return ("unop", node.op, key(node.operand))
        if isinstance(node, A.Concat):
            return ("concat", tuple(key(p) for p in node.parts))
        if isinstance(node, A.Interval):
            return ("interval", key(node.value), node.unit)
        if isinstance(node, A.DateAdd):
            return ("dateadd", key(node.base), key(node.amount), node.unit)
        if isinstance(node, A.FunctionCall):
            return ("func", node.name, tuple(key(a) for a in node.args))
        if isinstance(node, A.SelectItem):
            return ("item", key(node.expr), node.alias)
        if isinstance(node, A.Select):
            return ("select",
                    tuple(key(i) for i in node.items),
                    key(node.from_table), key(node.where),
                    key(node.limit), key(node.offset))
        raise TypeError(f"未知节点 {type(node).__name__}")
    return key(stmt)


def _diff_keys(path: str, expected, actual, out: list[str]) -> None:
    """递归比较两个 canonical key，收集可读差异。"""
    if expected == actual:
        return
    if (isinstance(expected, tuple) and isinstance(actual, tuple)
            and len(expected) == len(actual)
            and expected and actual and expected[0] == actual[0]
            and isinstance(expected[0], str)):
        for i, (e, a) in enumerate(zip(expected[1:], actual[1:])):
            _diff_keys(f"{path}.{expected[0]}[{i}]", e, a, out)
        return
    out.append(f"{path}: 期望 {expected!r}，实际 {actual!r}")


# ---------- 转译器 ----------

_WS = re.compile(r"\s+")


def _cache_sql_key(sql: str) -> str:
    return _WS.sub(" ", sql.strip())


class Transpiler:
    """线程安全的转译器。缓存键覆盖方言组合、规则版本与注册代际。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple, str] = {}

    def transpile(self, sql: str, source: str, target: str) -> TranspileResult:
        src = get_dialect(source)
        tgt = get_dialect(target)
        key = (_cache_sql_key(sql), src.name, tgt.name,
               src.version, tgt.version, registry_generation())
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None:
            return TranspileResult(sql=hit, source=src.name,
                                   target=tgt.name, cached=True)
        stmt = normalize(parse(sql), src)
        out = generate(stmt, tgt)
        with self._lock:
            self._cache[key] = out
        return TranspileResult(sql=out, source=src.name, target=tgt.name)

    def validate_roundtrip(self, sql: str, source: str,
                           target: str) -> RoundTripReport:
        src = get_dialect(source)
        first = self.transpile(sql, source, target)
        back = self.transpile(first.sql, target, source)
        report = RoundTripReport(ok=False, source_sql=sql,
                                 target_sql=first.sql,
                                 roundtrip_sql=back.sql)
        original = canonical_key(normalize(parse(sql), src))
        roundtripped = canonical_key(normalize(parse(back.sql), src))
        diffs: list[str] = []
        _diff_keys("select", original, roundtripped, diffs)
        report.differences = diffs
        report.ok = not diffs
        return report

    def clear_cache(self) -> None:
        with self._lock:
            self._cache.clear()

    @property
    def cache_size(self) -> int:
        with self._lock:
            return len(self._cache)
