"""SQL 解析器：将 token 流解析为 AST。

支持 SELECT 语句：列、别名、FROM、WHERE、ORDER BY、分页子句
（LIMIT/OFFSET、LIMIT a,b、TOP n、OFFSET/FETCH），以及表达式：
字面量、占位符、标识符、函数调用、CASE、INTERVAL、二元/一元运算。

所有方言共用此解析器；方言差异（引用符、占位符样式等）在词法层
已被归一，AST 层只保留规范形式。
"""

from __future__ import annotations

from typing import List, Optional, Tuple

from .ast_nodes import (
    BinaryOp, BooleanLiteral, CaseExpr, Column, Expr, FuncCall, Identifier,
    Interval, NullLiteral, NumberLiteral, OrderItem, Placeholder, Select,
    SelectItem, Star, StringLiteral, Subquery, UnaryOp,
)
from .errors import SqlSyntaxError
from .tokenizer import EOF, IDENT, KEYWORD, NUMBER, PLACEHOLDER, PUNCT, QIDENT, STRING, OP, Token, tokenize

# 在表达式位置可作为普通标识符使用的上下文关键字
_CONTEXT_IDENT_KEYWORDS = {"FIRST", "NEXT", "ROWS", "ONLY", "TOP"}

_INTERVAL_UNITS = {
    "DAY", "DAYS", "HOUR", "HOURS", "MINUTE", "MINUTES", "SECOND", "SECONDS",
    "MONTH", "MONTHS", "YEAR", "YEARS", "WEEK", "WEEKS",
}


def parse(sql: str) -> Select:
    """解析单条 SELECT 语句，语法错误时抛出 SqlSyntaxError（带位置）。"""
    parser = _Parser(tokenize(sql))
    stmt = parser.parse_statement()
    parser.expect_kind(EOF, "unexpected trailing input")
    return stmt


class _Parser:
    def __init__(self, tokens: List[Token]):
        self.tokens = tokens
        self.i = 0
        self._placeholder_count = 0

    # ------------------------------------------------------------------
    # 基础工具
    # ------------------------------------------------------------------

    @property
    def cur(self) -> Token:
        return self.tokens[self.i]

    def advance(self) -> Token:
        tok = self.tokens[self.i]
        if tok.kind != EOF:
            self.i += 1
        return tok

    def error(self, message: str, tok: Optional[Token] = None) -> SqlSyntaxError:
        tok = tok or self.cur
        return SqlSyntaxError(message, position=tok.pos)

    def expect_kind(self, kind: str, message: str, text: Optional[str] = None) -> Token:
        tok = self.cur
        if tok.kind != kind or (text is not None and tok.text != text):
            raise self.error(f"{message}, found {(tok.text or 'end of input')!r}")
        return self.advance()

    def accept_keyword(self, word: str) -> Optional[Token]:
        if self.cur.kind == KEYWORD and self.cur.text == word:
            return self.advance()
        return None

    def expect_keyword(self, word: str) -> Token:
        tok = self.accept_keyword(word)
        if tok is None:
            raise self.error(f"expected {word}, found {(self.cur.text or 'end of input')!r}")
        return tok

    def accept_punct(self, ch: str) -> Optional[Token]:
        if self.cur.kind == PUNCT and self.cur.text == ch:
            return self.advance()
        return None

    def accept_op(self, op: str) -> Optional[Token]:
        if self.cur.kind == OP and self.cur.text == op:
            return self.advance()
        return None

    # ------------------------------------------------------------------
    # 语句
    # ------------------------------------------------------------------

    def parse_statement(self) -> Select:
        self.expect_keyword("SELECT")
        top: Optional[Expr] = None
        if self.accept_keyword("TOP"):
            top = self.parse_unary()  # TOP n（mssql 风格）
        columns = self.parse_select_list()
        from_table = None
        if self.accept_keyword("FROM"):
            from_table = self.parse_identifier()
        where = None
        if self.accept_keyword("WHERE"):
            where = self.parse_expr()
        order_by: Tuple[OrderItem, ...] = ()
        if self.accept_keyword("ORDER"):
            self.expect_keyword("BY")
            order_by = self.parse_order_list()
        limit, offset = top, None
        # LIMIT n | LIMIT n OFFSET m | LIMIT m, n
        if self.accept_keyword("LIMIT"):
            first = self.parse_unary()
            if self.accept_punct(","):
                offset, limit = first, self.parse_unary()
            else:
                limit = first
                if self.accept_keyword("OFFSET"):
                    offset = self.parse_unary()
        # OFFSET m [ROWS] [FETCH FIRST|NEXT n ROWS ONLY]
        if self.accept_keyword("OFFSET"):
            offset = self.parse_unary()
            self.accept_keyword("ROWS")
        if self.accept_keyword("FETCH"):
            if not (self.accept_keyword("FIRST") or self.accept_keyword("NEXT")):
                raise self.error("expected FIRST or NEXT after FETCH")
            limit = self.parse_unary()
            self.expect_keyword("ROWS")
            self.expect_keyword("ONLY")
        self._check_non_negative(limit, "LIMIT")
        self._check_non_negative(offset, "OFFSET")
        return Select(columns=columns, from_table=from_table, where=where,
                      order_by=order_by, limit=limit, offset=offset)

    def _check_non_negative(self, expr: Optional[Expr], clause: str) -> None:
        """分页参数为负属于确定性的非法输入，解析期即报错。"""
        if isinstance(expr, NumberLiteral):
            try:
                if float(expr.value) < 0:
                    raise SqlSyntaxError(f"{clause} must not be negative")
            except ValueError:
                pass

    def parse_select_list(self) -> Tuple[SelectItem, ...]:
        items = [self.parse_select_item()]
        while self.accept_punct(","):
            items.append(self.parse_select_item())
        return tuple(items)

    def parse_select_item(self) -> SelectItem:
        expr = self.parse_expr()
        alias = None
        if self.accept_keyword("AS"):
            alias = self.parse_identifier()
        elif self.cur.kind in (IDENT, QIDENT):
            alias = self.parse_identifier()
        return SelectItem(expr=expr, alias=alias)

    def parse_order_list(self) -> Tuple[OrderItem, ...]:
        items = [self.parse_order_item()]
        while self.accept_punct(","):
            items.append(self.parse_order_item())
        return tuple(items)

    def parse_order_item(self) -> OrderItem:
        expr = self.parse_expr()
        descending = False
        if self.accept_keyword("DESC"):
            descending = True
        else:
            self.accept_keyword("ASC")
        return OrderItem(expr=expr, descending=descending)

    # ------------------------------------------------------------------
    # 表达式（按优先级分层）
    # ------------------------------------------------------------------

    def parse_expr(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        left = self.parse_and()
        while self.accept_keyword("OR"):
            left = BinaryOp("OR", left, self.parse_and())
        return left

    def parse_and(self) -> Expr:
        left = self.parse_not()
        while self.accept_keyword("AND"):
            left = BinaryOp("AND", left, self.parse_not())
        return left

    def parse_not(self) -> Expr:
        if self.accept_keyword("NOT"):
            return UnaryOp("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Expr:
        left = self.parse_concat()
        tok = self.cur
        if tok.kind == OP and tok.text in ("=", "<>", "!=", "<", "<=", ">", ">="):
            self.advance()
            op = "<>" if tok.text == "!=" else tok.text
            return BinaryOp(op, left, self.parse_concat())
        if self.accept_keyword("LIKE"):
            return BinaryOp("LIKE", left, self.parse_concat())
        if self.accept_keyword("IS"):
            negated = bool(self.accept_keyword("NOT"))
            right = self.parse_concat()
            return BinaryOp("IS NOT" if negated else "IS", left, right)
        return left

    def parse_concat(self) -> Expr:
        left = self.parse_additive()
        while self.accept_op("||"):
            left = BinaryOp("CONCAT", left, self.parse_additive())
        return left

    def parse_additive(self) -> Expr:
        left = self.parse_multiplicative()
        while True:
            if self.accept_op("+"):
                left = self._arith("DATE_ADD", "+", left)
            elif self.accept_op("-"):
                left = self._arith("DATE_SUB", "-", left)
            else:
                return left

    def _arith(self, date_op: str, plain_op: str, left: Expr) -> Expr:
        """右操作数为 INTERVAL 时归一为日期运算节点，否则为普通算术。"""
        right = self.parse_multiplicative()
        if isinstance(right, Interval):
            return BinaryOp(date_op, left, right)
        if isinstance(left, Interval) and date_op == "DATE_ADD":
            return BinaryOp(date_op, right, left)
        return BinaryOp(plain_op, left, right)

    def parse_multiplicative(self) -> Expr:
        left = self.parse_unary()
        while True:
            for op in ("*", "/", "%"):
                if self.accept_op(op):
                    left = BinaryOp(op, left, self.parse_unary())
                    break
            else:
                return left

    def parse_unary(self) -> Expr:
        if self.accept_op("-"):
            operand = self.parse_unary()
            # 负数字面量折叠，保证分页等场景的确定性判断
            if isinstance(operand, NumberLiteral):
                return NumberLiteral("-" + operand.value)
            return UnaryOp("NEG", operand)
        if self.accept_op("+"):
            return self.parse_unary()
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        tok = self.cur
        if tok.kind == NUMBER:
            self.advance()
            return NumberLiteral(tok.text)
        if tok.kind == STRING:
            self.advance()
            return StringLiteral(tok.text)
        if tok.kind == PLACEHOLDER:
            self.advance()
            idx = self._placeholder_count
            self._placeholder_count += 1
            name = tok.text[1:] if tok.text.startswith(":") else None
            return Placeholder(index=idx, name=name)
        if tok.kind == KEYWORD:
            if tok.text in ("TRUE", "FALSE"):
                self.advance()
                return BooleanLiteral(tok.text == "TRUE")
            if tok.text == "NULL":
                self.advance()
                return NullLiteral()
            if tok.text == "CASE":
                return self.parse_case()
            if tok.text == "INTERVAL":
                return self.parse_interval()
        if tok.kind == PUNCT and tok.text == "(":
            self.advance()
            if self.cur.kind == KEYWORD and self.cur.text == "SELECT":
                sub = Subquery(self.parse_statement())
                self.expect_kind(PUNCT, "expected )", ")")
                return sub
            expr = self.parse_expr()
            self.expect_kind(PUNCT, "expected )", ")")
            return expr
        if tok.kind == OP and tok.text == "*":
            self.advance()
            return Star()
        if tok.kind in (IDENT, QIDENT):
            return self.parse_ident_or_call()
        if tok.kind == KEYWORD and tok.text in _CONTEXT_IDENT_KEYWORDS:
            return self.parse_ident_or_call()
        raise self.error(f"unexpected token {(tok.text or 'end of input')!r}")

    def parse_case(self) -> Expr:
        self.expect_keyword("CASE")
        whens = []
        while self.accept_keyword("WHEN"):
            cond = self.parse_expr()
            self.expect_keyword("THEN")
            whens.append((cond, self.parse_expr()))
        if not whens:
            raise self.error("CASE requires at least one WHEN")
        else_ = None
        if self.accept_keyword("ELSE"):
            else_ = self.parse_expr()
        self.expect_keyword("END")
        return CaseExpr(whens=tuple(whens), else_=else_)

    def parse_interval(self) -> Interval:
        self.expect_keyword("INTERVAL")
        tok = self.cur
        if tok.kind == STRING:
            # postgres 风格：INTERVAL '1 day'
            self.advance()
            parts = tok.text.split()
            if len(parts) != 2 or parts[1].upper() not in _INTERVAL_UNITS:
                raise self.error(
                    f"invalid INTERVAL literal {tok.text!r}, expected e.g. '1 day'",
                    tok,
                )
            return Interval(NumberLiteral(parts[0]), _norm_unit(parts[1]))
        value = self.parse_primary()
        unit_tok = self.cur
        if unit_tok.kind == IDENT and unit_tok.text.upper() in _INTERVAL_UNITS:
            self.advance()
            return Interval(value, _norm_unit(unit_tok.text))
        raise self.error("expected interval unit (DAY, HOUR, ...) after INTERVAL value")

    def parse_ident_or_call(self) -> Expr:
        ident = self.parse_identifier()
        if self.accept_punct("("):
            args: List[Expr] = []
            if not self.accept_punct(")"):
                args.append(self.parse_expr())
                while self.accept_punct(","):
                    args.append(self.parse_expr())
                self.expect_kind(PUNCT, "expected )", ")")
            return FuncCall(name=ident.name.upper(), args=tuple(args))
        if self.accept_punct("."):
            col = self.parse_identifier()
            return Column(name=col, table=ident)
        return Column(name=ident)

    def parse_identifier(self) -> Identifier:
        tok = self.cur
        if tok.kind == IDENT:
            self.advance()
            # 未加引号的标识符统一折叠为小写，保证书写风格不影响结果
            return Identifier(name=tok.text.lower(), quoted=False)
        if tok.kind == QIDENT:
            self.advance()
            return Identifier(name=tok.text, quoted=True)
        if tok.kind == KEYWORD and tok.text in _CONTEXT_IDENT_KEYWORDS:
            self.advance()
            return Identifier(name=tok.text.lower(), quoted=False)
        raise self.error(f"expected identifier, found {(tok.text or 'end of input')!r}")


def _norm_unit(unit: str) -> str:
    u = unit.upper()
    return u[:-1] if u.endswith("S") else u
