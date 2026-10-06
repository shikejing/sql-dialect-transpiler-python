"""SQL 生成器：把规范化后的 AST 按目标方言规则渲染为 SQL 文本。

所有方言差异（引用符、占位符、布尔字面量、拼接、分页、日期运算、
函数重写）都在此依据 Dialect 规则落实，不做任何关键字级字符串替换。
"""

from __future__ import annotations

from typing import List

from .ast_nodes import (
    BinaryOp, BooleanLiteral, CaseExpr, Column, Expr, FuncCall, Identifier,
    Interval, NullLiteral, NumberLiteral, Placeholder, Select, Star,
    StringLiteral, Subquery, UnaryOp,
)
from .dialects import (
    CONCAT_FUNCTION, CONCAT_OPERATOR, CONCAT_PLUS, DATE_DATEADD, DATE_FUNC,
    DATE_INTERVAL, DATE_MODIFIER, PAGE_LIMIT_OFFSET, PAGE_TOP, PH_FORMAT,
    PH_NAMED, PH_NUMERIC, PH_QMARK, RENAME, TEMPLATE, UNSUPPORTED, Dialect,
)
from .errors import UnsupportedFeatureError

# 表达式中二元运算符的优先级（用于确定性加括号，保证往返解析结构一致）
_PRECEDENCE = {
    "OR": 1,
    "AND": 2,
    "=": 3, "<>": 3, "<": 3, "<=": 3, ">": 3, ">=": 3, "LIKE": 3,
    "IS": 3, "IS NOT": 3,
    "CONCAT": 4,
    "+": 5, "-": 5, "DATE_ADD": 5, "DATE_SUB": 5,
    "*": 6, "/": 6, "%": 6,
}


class Generator:
    def __init__(self, dialect: Dialect, source_name: str = "*"):
        self.dialect = dialect
        self.source_name = source_name

    # ------------------------------------------------------------------
    # 语句
    # ------------------------------------------------------------------

    def render(self, stmt: Select) -> str:
        parts: List[str] = ["SELECT"]
        limit, offset = stmt.limit, stmt.offset
        if (self.dialect.pagination == PAGE_TOP and limit is not None
                and (offset is None or self._is_zero(offset))):
            # TOP 只覆盖无偏移的分页；有偏移时走 OFFSET/FETCH
            parts.append(f"TOP {self.render_expr(limit)}")
            limit = None
        parts.append(", ".join(self.render_select_item(c) for c in stmt.columns))
        if stmt.from_table is not None:
            parts.append(f"FROM {self.render_identifier(stmt.from_table)}")
        if stmt.where is not None:
            parts.append(f"WHERE {self.render_expr(stmt.where)}")
        order_by = stmt.order_by
        if self.dialect.pagination == PAGE_TOP and (limit is not None or (offset is not None and not self._is_zero(offset))):
            # OFFSET/FETCH 语法要求 ORDER BY；缺失时补确定性常量排序键
            if not order_by:
                parts.append("ORDER BY (SELECT NULL)")
        if order_by:
            parts.append("ORDER BY " + ", ".join(
                self.render_expr(o.expr) + (" DESC" if o.descending else "")
                for o in order_by))
        parts.extend(self.render_pagination(limit, offset))
        return " ".join(p for p in parts if p)

    def render_pagination(self, limit, offset) -> List[str]:
        out: List[str] = []
        has_offset = offset is not None and not self._is_zero(offset)
        if self.dialect.pagination == PAGE_LIMIT_OFFSET:
            if limit is not None:
                out.append(f"LIMIT {self.render_expr(limit)}")
            if has_offset:
                out.append(f"OFFSET {self.render_expr(offset)}")
        elif self.dialect.pagination == PAGE_TOP:
            if has_offset:
                out.append(f"OFFSET {self.render_expr(offset)} ROWS")
                if limit is not None:
                    out.append(f"FETCH NEXT {self.render_expr(limit)} ROWS ONLY")
            elif limit is not None:
                out.append(f"OFFSET 0 ROWS FETCH NEXT {self.render_expr(limit)} ROWS ONLY")
        return out

    @staticmethod
    def _is_zero(expr) -> bool:
        return isinstance(expr, NumberLiteral) and float(expr.value) == 0

    def render_select_item(self, item) -> str:
        sql = self.render_expr(item.expr)
        if item.alias is not None:
            sql += f" AS {self.render_identifier(item.alias)}"
        return sql

    # ------------------------------------------------------------------
    # 表达式
    # ------------------------------------------------------------------

    def render_expr(self, expr: Expr, parent_prec: int = 0) -> str:
        if isinstance(expr, NumberLiteral):
            return expr.value
        if isinstance(expr, StringLiteral):
            return "'" + expr.value.replace("'", "''") + "'"
        if isinstance(expr, BooleanLiteral):
            if self.dialect.native_boolean:
                return "TRUE" if expr.value else "FALSE"
            return "1" if expr.value else "0"
        if isinstance(expr, NullLiteral):
            return "NULL"
        if isinstance(expr, Placeholder):
            return self.render_placeholder(expr)
        if isinstance(expr, Star):
            return "*"
        if isinstance(expr, Subquery):
            return "(" + self.render(expr.stmt) + ")"
        if isinstance(expr, Column):
            if expr.table is not None:
                return f"{self.render_identifier(expr.table)}.{self.render_identifier(expr.name)}"
            return self.render_identifier(expr.name)
        if isinstance(expr, FuncCall):
            return self.render_func(expr)
        if isinstance(expr, Interval):
            return self.render_interval_literal(expr)
        if isinstance(expr, CaseExpr):
            parts = ["CASE"]
            for cond, val in expr.whens:
                parts.append(f"WHEN {self.render_expr(cond)} THEN {self.render_expr(val)}")
            if expr.else_ is not None:
                parts.append(f"ELSE {self.render_expr(expr.else_)}")
            parts.append("END")
            return " ".join(parts)
        if isinstance(expr, UnaryOp):
            inner = self.render_expr(expr.operand, parent_prec=7)
            return f"NOT {inner}" if expr.op == "NOT" else f"-{inner}"
        if isinstance(expr, BinaryOp):
            return self.render_binary(expr, parent_prec)
        raise UnsupportedFeatureError(
            f"ast node {type(expr).__name__}",
            source=self.source_name, target=self.dialect.name,
            reason="generator does not handle this node type",
        )

    def render_binary(self, expr: BinaryOp, parent_prec: int) -> str:
        if expr.op in ("DATE_ADD", "DATE_SUB"):
            return self.render_date_arith(expr)
        prec = _PRECEDENCE[expr.op]
        if expr.op == "CONCAT":
            sql = self.render_concat(expr.left, expr.right, prec)
        else:
            sql = f"{self.render_expr(expr.left, prec)} {expr.op} {self.render_expr(expr.right, prec + 1)}"
        if prec < parent_prec:
            return f"({sql})"
        return sql

    def render_concat(self, left: Expr, right: Expr, prec: int) -> str:
        operands = self._flatten_concat(BinaryOp("CONCAT", left, right))
        style = self.dialect.concat_style
        if style == CONCAT_OPERATOR:
            return " || ".join(self.render_expr(o, prec) for o in operands)
        if style == CONCAT_PLUS:
            return " + ".join(self.render_expr(o, prec) for o in operands)
        if style == CONCAT_FUNCTION:
            return "CONCAT(" + ", ".join(self.render_expr(o) for o in operands) + ")"
        raise UnsupportedFeatureError(
            "string concatenation", source=self.source_name, target=self.dialect.name,
            reason=f"unknown concat style {style!r}")

    def _flatten_concat(self, expr: Expr) -> List[Expr]:
        if isinstance(expr, BinaryOp) and expr.op == "CONCAT":
            return self._flatten_concat(expr.left) + self._flatten_concat(expr.right)
        return [expr]

    # ------------------------------------------------------------------
    # 日期时间运算
    # ------------------------------------------------------------------

    def render_date_arith(self, expr: BinaryOp) -> str:
        base, interval = expr.left, expr.right
        assert isinstance(interval, Interval)
        sign = "-" if expr.op == "DATE_SUB" else "+"
        style = self.dialect.date_arith
        unit = interval.unit
        value_sql = self.render_expr(interval.value)

        if style == DATE_INTERVAL:
            return f"{self.render_expr(base, 5)} {sign} INTERVAL '{value_sql} {unit.lower()}'"
        if style == DATE_FUNC:
            func = "DATE_ADD" if sign == "+" else "DATE_SUB"
            return f"{func}({self.render_expr(base)}, INTERVAL {value_sql} {unit})"
        if style == DATE_DATEADD:
            n = value_sql if sign == "+" else f"-({value_sql})"
            return f"DATEADD({unit.lower()}, {n}, {self.render_expr(base)})"
        if style == DATE_MODIFIER:
            modifier = self._sqlite_modifier(sign, value_sql, unit, expr)
            return f"datetime({self.render_expr(base)}, '{modifier}')"
        raise UnsupportedFeatureError(
            "date arithmetic", source=self.source_name, target=self.dialect.name,
            reason=f"unknown date arithmetic style {style!r}")

    def _sqlite_modifier(self, sign: str, value_sql: str, unit: str, node: Expr) -> str:
        """sqlite 修饰符不支持 WEEK，确定性地换算为 7 倍天数。"""
        if unit == "WEEK":
            if isinstance(node.right.value, NumberLiteral):
                days = float(node.right.value.value) * 7
                days_sql = str(int(days)) if days == int(days) else str(days)
            else:
                days_sql = f"7 * ({value_sql})"
            return f"{sign}{days_sql} days"
        return f"{sign}{value_sql} {unit.lower()}s"

    def render_interval_literal(self, expr: Interval) -> str:
        # 独立的 INTERVAL 字面量（不出现在日期运算中）
        value_sql = self.render_expr(expr.value)
        if self.dialect.date_arith == DATE_INTERVAL:
            return f"INTERVAL '{value_sql} {expr.unit.lower()}'"
        if self.dialect.date_arith == DATE_MODIFIER:
            raise UnsupportedFeatureError(
                "standalone INTERVAL literal", source=self.source_name, target=self.dialect.name,
                reason="sqlite only supports intervals inside date functions")
        return f"INTERVAL {value_sql} {expr.unit}"

    # ------------------------------------------------------------------
    # 函数
    # ------------------------------------------------------------------

    def render_func(self, call: FuncCall) -> str:
        name = call.name
        if name == "CONCAT":
            operands = ", ".join(self.render_expr(a) for a in call.args)
            style = self.dialect.concat_style
            if style == CONCAT_FUNCTION:
                return f"CONCAT({operands})"
            sep = " || " if style == CONCAT_OPERATOR else " + "
            return sep.join(self.render_expr(a, _PRECEDENCE["CONCAT"]) for a in call.args)
        rule = self.dialect.function_rules.get(name)
        if rule is not None:
            if rule.kind == UNSUPPORTED:
                raise UnsupportedFeatureError(
                    f"function {name}", source=self.source_name, target=self.dialect.name,
                    reason=rule.reason)
            if rule.kind == RENAME:
                args = ", ".join(self.render_expr(a) for a in call.args)
                return f"{rule.value}({args})"
            if rule.kind == TEMPLATE:
                rendered = [self.render_expr(a) for a in call.args]
                try:
                    return rule.value.format(*rendered)
                except IndexError:
                    raise UnsupportedFeatureError(
                        f"function {name}", source=self.source_name, target=self.dialect.name,
                        reason=f"expected more arguments for template {rule.value!r}")
        args = ", ".join(self.render_expr(a) for a in call.args)
        if name == "CURRENT_TIMESTAMP" and not call.args:
            return "CURRENT_TIMESTAMP"
        return f"{name}({args})"

    # ------------------------------------------------------------------
    # 标识符与占位符
    # ------------------------------------------------------------------

    def render_identifier(self, ident: Identifier) -> str:
        if ident.quoted:
            qo, qc = self.dialect.quote_open, self.dialect.quote_close
            return qo + ident.name.replace(qc, qc + qc) + qc
        return ident.name

    def render_placeholder(self, ph: Placeholder) -> str:
        style = self.dialect.placeholder
        n = ph.index + 1
        if style == PH_QMARK:
            return "?"
        if style == PH_NUMERIC:
            return f"${n}"
        if style == PH_FORMAT:
            return "%s"
        if style == PH_NAMED:
            return f"@p{n}"
        raise UnsupportedFeatureError(
            "placeholder", source=self.source_name, target=self.dialect.name,
            reason=f"unknown placeholder style {style!r}")
