"""AST -> 目标方言 SQL 文本。

标识符大小写折叠在 engine 的规范化阶段按源方言规则完成，
生成器只负责按目标方言规则输出引用形式与方言结构。
"""
from __future__ import annotations

from .ast_nodes import (BinaryOp, BooleanLiteral, Concat, DateAdd,
                        FunctionCall, Identifier, Interval, Literal, Node,
                        Placeholder, QualifiedName, Select, UnaryOp)
from .dialects import DialectRules
from .errors import UnsupportedFeatureError

# 运算符优先级（越大越紧）
_PRECEDENCE = {
    "OR": 1, "AND": 2, "NOT": 3,
    "=": 4, "<": 4, ">": 4, "<=": 4, ">=": 4, "<>": 4,
    "+": 5, "-": 5, "*": 6, "/": 6,
}


class Generator:
    def __init__(self, rules: DialectRules) -> None:
        self.rules = rules

    # ---------- 语句 ----------

    def generate(self, stmt: Select) -> str:
        parts = ["SELECT " + ", ".join(self._select_item(i) for i in stmt.items)]
        if stmt.from_table is not None:
            parts.append("FROM " + self._expr(stmt.from_table))
        if stmt.where is not None:
            parts.append("WHERE " + self._expr(stmt.where))
        pagination = self._pagination(stmt)
        if pagination:
            parts.append(pagination)
        return " ".join(parts)

    def _select_item(self, item) -> str:
        sql = self._expr(item.expr)
        if item.alias:
            sql += " AS " + self._quote_ident(item.alias)
        return sql

    def _pagination(self, stmt: Select) -> str:
        limit, offset = stmt.limit, stmt.offset
        if limit is None and offset is None:
            return ""
        off_zero = isinstance(offset, Literal) and offset.value == 0
        if self.rules.pagination_style == "offset_fetch":
            # SQL Server: OFFSET n ROWS [FETCH NEXT m ROWS ONLY]，OFFSET 不可省略
            off_sql = "0" if (offset is None or off_zero) else self._expr(offset)
            sql = f"OFFSET {off_sql} ROWS"
            if limit is not None:
                sql += f" FETCH NEXT {self._expr(limit)} ROWS ONLY"
            return sql
        # limit_offset 样式
        if limit is None:
            # 仅 OFFSET：用方言的极限行数哨兵，行为确定
            return f"LIMIT {self.rules.limit_all_token} OFFSET {self._expr(offset)}"
        sql = f"LIMIT {self._expr(limit)}"
        if offset is not None and not off_zero:
            sql += f" OFFSET {self._expr(offset)}"
        return sql

    # ---------- 表达式 ----------

    def _expr(self, node: Node, parent_prec: int = 0) -> str:
        sql, prec = self._expr_inner(node)
        if prec < parent_prec:
            return f"({sql})"
        return sql

    def _expr_inner(self, node: Node) -> tuple[str, int]:
        if isinstance(node, Identifier):
            return self._quote_ident(node.name), 10
        if isinstance(node, QualifiedName):
            return ".".join(self._quote_ident(p) for p in node.parts), 10
        if isinstance(node, Literal):
            return self._literal(node), 10
        if isinstance(node, BooleanLiteral):
            return self.rules.bool_literals[0 if node.value else 1], 10
        if isinstance(node, Placeholder):
            return self._placeholder(node.index), 10
        if isinstance(node, Concat):
            return self._concat(node), 5
        if isinstance(node, DateAdd):
            return self._date_add(node), 5
        if isinstance(node, FunctionCall):
            return self._function(node), 10
        if isinstance(node, UnaryOp):
            if node.op == "NOT":
                return f"NOT {self._expr(node.operand, _PRECEDENCE['NOT'])}", _PRECEDENCE["NOT"]
            return f"-{self._expr(node.operand, 7)}", 7
        if isinstance(node, BinaryOp):
            prec = _PRECEDENCE[node.op]
            left = self._expr(node.left, prec)
            right = self._expr(node.right, prec + 1)
            return f"{left} {node.op} {right}", prec
        raise UnsupportedFeatureError(f"不支持的 AST 节点 {type(node).__name__}")

    def _quote_ident(self, name: str) -> str:
        r = self.rules
        return f"{r.ident_quote_open}{name}{r.ident_quote_close}"

    def _literal(self, node: Literal) -> str:
        if node.kind == "null":
            return "NULL"
        if node.kind == "string":
            return "'" + str(node.value).replace("'", "''") + "'"
        return str(node.value)

    def _placeholder(self, index: int) -> str:
        style = self.rules.placeholder_style
        if style == "qmark":
            return "?"
        if style == "format":
            return "%s"
        if style == "numeric_dollar":
            return f"${index + 1}"
        if style == "named_at":
            return f"@p{index + 1}"
        raise UnsupportedFeatureError(f"未知占位符样式 {style!r}")

    def _concat(self, node: Concat) -> str:
        if self.rules.concat_style == "function":
            return "CONCAT(" + ", ".join(self._expr(p) for p in node.parts) + ")"
        return " || ".join(self._expr(p, 5) for p in node.parts)

    def _signed_amount(self, node: DateAdd) -> tuple[str, object]:
        """把 amount 折叠为 (符号, 非负表达式文本)。"""
        amount = node.amount
        if isinstance(amount, Literal) and amount.kind == "number":
            if amount.value < 0:
                return "-", str(-amount.value)
            return "+", str(amount.value)
        if isinstance(amount, UnaryOp) and amount.op == "-":
            inner = amount.operand
            if isinstance(inner, Literal) and inner.kind == "number":
                return "-", str(inner.value)
            return "-", self._expr(inner)
        return "+", self._expr(amount)

    def _date_add(self, node: DateAdd) -> str:
        style = self.rules.date_arith_style
        base = self._expr(node.base, 5)
        sign, amount = self._signed_amount(node)
        unit = node.unit
        if style == "interval_op":
            # 字面量直接写进 INTERVAL 字符串；表达式用 INTERVAL '1 u' * x
            amt = node.amount
            is_literal = isinstance(amt, Literal) or (
                isinstance(amt, UnaryOp) and amt.op == "-"
                and isinstance(amt.operand, Literal))
            if is_literal:
                interval = f"INTERVAL '{amount} {unit}'"
            else:
                interval = f"(INTERVAL '1 {unit}' * {amount})"
            op = "+" if sign == "+" else "-"
            return f"{base} {op} {interval}"
        elif style == "interval_kw":
            func = "DATE_ADD" if sign == "+" else "DATE_SUB"
            return f"{func}({self._expr(node.base)}, INTERVAL {amount} {unit.upper()})"
        elif style == "dateadd":
            amt = amount if sign == "+" else f"-({amount})"
            return f"DATEADD({unit}, {amt}, {self._expr(node.base)})"
        elif style == "datetime_mod":
            amt = node.amount
            is_literal = isinstance(amt, Literal) or (
                isinstance(amt, UnaryOp) and amt.op == "-"
                and isinstance(amt.operand, Literal))
            if not is_literal:
                raise UnsupportedFeatureError(
                    "sqlite 的 datetime() 日期加减只支持常量间隔，"
                    "动态间隔在该方言下无法保证语义等价")
            return f"datetime({self._expr(node.base)}, '{sign}{amount} {unit}')"
        raise UnsupportedFeatureError(f"未知日期运算样式 {style!r}")

    def _function(self, node: FunctionCall) -> str:
        target = self.rules.function_map.get(node.name)
        if target is None:
            raise UnsupportedFeatureError(
                f"函数 {node.name!r} 在方言 {self.rules.name!r} 中无等价实现")
        args = ", ".join(self._expr(a) for a in node.args)
        if target == "":
            return args  # 映射为空串表示目标方言无需函数包裹
        return f"{target}({args})"


def generate(stmt: Select, rules: DialectRules) -> str:
    return Generator(rules).generate(stmt)
