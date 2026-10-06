"""SQL 抽象语法树节点定义。

转译基于语法结构：源方言解析为 AST，再由目标方言的生成器输出。
所有节点为不可变 dataclass，结构相等即可比较（用于往返校验）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Tuple, Union


# ---------------------------------------------------------------------------
# 表达式节点
# ---------------------------------------------------------------------------

class Expr:
    """表达式节点基类。"""


@dataclass(frozen=True)
class NumberLiteral(Expr):
    value: str  # 保留原始文本，避免浮点精度问题


@dataclass(frozen=True)
class StringLiteral(Expr):
    value: str  # 已去除引号、反转义后的值


@dataclass(frozen=True)
class BooleanLiteral(Expr):
    value: bool


@dataclass(frozen=True)
class NullLiteral(Expr):
    pass


@dataclass(frozen=True)
class Placeholder(Expr):
    """参数占位符。index 为出现顺序（从 0 开始），name 为命名占位符名。"""

    index: int
    name: Optional[str] = None


@dataclass(frozen=True)
class Identifier(Expr):
    """标识符。quoted 记录源语句中是否显式引用，name 为折叠后的规范名。"""

    name: str
    quoted: bool = False


@dataclass(frozen=True)
class Column(Expr):
    """列引用，可带表前缀。"""

    name: Identifier
    table: Optional[Identifier] = None


@dataclass(frozen=True)
class FuncCall(Expr):
    """函数调用。name 统一存大写规范名。"""

    name: str
    args: Tuple[Expr, ...] = ()


@dataclass(frozen=True)
class BinaryOp(Expr):
    """二元运算。op 为规范名：算术 + - * / %，比较 = <> < <= > >=，
    逻辑 AND OR，字符串拼接 CONCAT，日期加减 DATE_ADD DATE_SUB。"""

    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class UnaryOp(Expr):
    op: str  # NOT / NEG
    operand: Expr


@dataclass(frozen=True)
class Interval(Expr):
    """时间间隔字面量，如 INTERVAL 1 DAY。"""

    value: Expr
    unit: str  # DAY / HOUR / MONTH ... 统一大写


@dataclass(frozen=True)
class CaseExpr(Expr):
    """CASE WHEN ... THEN ... ELSE ... END。"""

    whens: Tuple[Tuple[Expr, Expr], ...]
    else_: Optional[Expr] = None


@dataclass(frozen=True)
class Star(Expr):
    pass


@dataclass(frozen=True)
class Subquery(Expr):
    """括号包裹的子查询。"""

    stmt: "Select"


# ---------------------------------------------------------------------------
# 语句节点
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SelectItem:
    expr: Expr
    alias: Optional[Identifier] = None


@dataclass(frozen=True)
class OrderItem:
    expr: Expr
    descending: bool = False


@dataclass(frozen=True)
class Select:
    columns: Tuple[SelectItem, ...]
    from_table: Optional[Identifier] = None
    where: Optional[Expr] = None
    order_by: Tuple[OrderItem, ...] = ()
    limit: Optional[Expr] = None
    offset: Optional[Expr] = None


Statement = Union[Select]
