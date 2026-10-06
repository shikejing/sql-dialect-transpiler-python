"""SQL 抽象语法树节点定义（与方言无关的中间表示）。"""
from __future__ import annotations

from dataclasses import dataclass, field


class Node:
    """AST 节点基类。"""


# ---------- 表达式 ----------

@dataclass
class Identifier(Node):
    name: str
    quoted: bool = False


@dataclass
class QualifiedName(Node):
    parts: list[str]
    quoted: bool = False


@dataclass
class Literal(Node):
    value: object  # int | float | str | None
    kind: str = "number"  # number | string | null


@dataclass
class BooleanLiteral(Node):
    value: bool = True


@dataclass
class Placeholder(Node):
    """参数占位符，index 从 0 开始按出现顺序编号。"""
    index: int = 0


@dataclass
class BinaryOp(Node):
    op: str = ""
    left: Node | None = None
    right: Node | None = None


@dataclass
class UnaryOp(Node):
    op: str = ""
    operand: Node | None = None


@dataclass
class Concat(Node):
    """字符串拼接（源中的 || 或 CONCAT(...)）。"""
    parts: list[Node] = field(default_factory=list)


@dataclass
class Interval(Node):
    value: Node | None = None
    unit: str = "day"


@dataclass
class DateAdd(Node):
    """日期时间加减；amount 为正为加、为负为减。"""
    base: Node | None = None
    amount: Node | None = None
    unit: str = "day"


@dataclass
class FunctionCall(Node):
    name: str = ""
    args: list[Node] = field(default_factory=list)


# ---------- 语句 ----------

@dataclass
class SelectItem(Node):
    expr: Node | None = None
    alias: str | None = None


@dataclass
class Select(Node):
    items: list[SelectItem] = field(default_factory=list)
    from_table: Node | None = None
    where: Node | None = None
    limit: Node | None = None
    offset: Node | None = None
