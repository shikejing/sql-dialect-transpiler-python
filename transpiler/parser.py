"""递归下降解析器：token 流 -> AST。语法错误抛出 SqlParseError（带位置）。"""
from __future__ import annotations

from .ast_nodes import (BinaryOp, BooleanLiteral, Concat, DateAdd,
                        FunctionCall, Identifier, Interval, Literal,
                        Placeholder, QualifiedName, Select, SelectItem,
                        UnaryOp)
from .errors import SqlParseError
from .tokenizer import Token, TokenType, tokenize

_KEYWORDS = {
    "SELECT", "FROM", "WHERE", "LIMIT", "OFFSET", "FETCH", "NEXT", "ROWS",
    "ONLY", "AND", "OR", "NOT", "AS", "TRUE", "FALSE", "NULL", "INTERVAL",
}

_INTERVAL_UNITS = {
    "DAY", "DAYS", "HOUR", "HOURS", "MINUTE", "MINUTES", "SECOND", "SECONDS",
    "MONTH", "MONTHS", "YEAR", "YEARS", "WEEK", "WEEKS",
}

# 方言专有函数名 -> 规范函数名
_FUNC_CANON = {
    "dateadd": "date_add",
    "date_add": "date_add",
    "date_sub": "date_sub",
    "group_concat": "string_agg",
    "string_agg": "string_agg",
    "len": "length",
    "char_length": "length",
    "character_length": "length",
    "length": "length",
    "substr": "substring",
    "substring": "substring",
    "now": "now",
    "current_timestamp": "now",
    "getdate": "now",
    "upper": "upper",
    "lower": "lower",
    "coalesce": "coalesce",
    "abs": "abs",
    "concat": "concat",
}


class Parser:
    def __init__(self, tokens: list[Token]) -> None:
        self.tokens = tokens
        self.pos = 0
        self._param_count = 0

    # ---------- 基础工具 ----------

    def _peek(self) -> Token:
        return self.tokens[self.pos]

    def _next(self) -> Token:
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def _error(self, msg: str, tok: Token | None = None) -> SqlParseError:
        tok = tok or self._peek()
        return SqlParseError(msg, position=tok.position)

    def _is_kw(self, word: str) -> bool:
        tok = self._peek()
        return tok.type == TokenType.IDENT and tok.value.upper() == word

    def _expect_kw(self, word: str) -> Token:
        if not self._is_kw(word):
            raise self._error(f"期望关键字 {word}，实际为 {self._peek().value!r}")
        return self._next()

    def _expect(self, ttype: TokenType, what: str) -> Token:
        tok = self._peek()
        if tok.type != ttype:
            raise self._error(f"期望{what}，实际为 {tok.value!r}")
        return self._next()

    # ---------- 语句 ----------

    def parse_select(self) -> Select:
        self._expect_kw("SELECT")
        stmt = Select()
        stmt.items = self._parse_select_list()
        if self._is_kw("FROM"):
            self._next()
            stmt.from_table = self._parse_name()
        if self._is_kw("WHERE"):
            self._next()
            stmt.where = self._parse_expr()
        self._parse_pagination(stmt)
        if self._peek().type != TokenType.EOF:
            raise self._error(f"语句末尾存在多余内容 {self._peek().value!r}")
        return stmt

    def _parse_name(self):
        tok = self._peek()
        if tok.type not in (TokenType.IDENT, TokenType.QIDENT):
            raise self._error(f"期望标识符，实际为 {tok.value!r}")
        self._next()
        parts = [tok.value]
        quoted = tok.type == TokenType.QIDENT
        while self._peek().type == TokenType.DOT:
            self._next()
            nxt = self._peek()
            if nxt.type not in (TokenType.IDENT, TokenType.QIDENT):
                raise self._error("限定标识符中 . 之后必须是标识符")
            self._next()
            parts.append(nxt.value)
            quoted = quoted or nxt.type == TokenType.QIDENT
        if len(parts) == 1:
            return Identifier(name=parts[0], quoted=quoted)
        return QualifiedName(parts=parts, quoted=quoted)

    def _parse_select_list(self) -> list[SelectItem]:
        items = [self._parse_select_item()]
        while self._peek().type == TokenType.COMMA:
            self._next()
            items.append(self._parse_select_item())
        return items

    def _parse_select_item(self) -> SelectItem:
        expr = self._parse_expr()
        alias = None
        if self._is_kw("AS"):
            self._next()
            tok = self._peek()
            if tok.type not in (TokenType.IDENT, TokenType.QIDENT):
                raise self._error("期望别名")
            alias = self._next().value
        elif (self._peek().type == TokenType.IDENT
              and self._peek().value.upper() not in _KEYWORDS):
            alias = self._next().value
        return SelectItem(expr=expr, alias=alias)

    def _parse_pagination(self, stmt: Select) -> None:
        if self._is_kw("LIMIT"):
            self._next()
            stmt.limit = self._parse_limit_value()
            if self._peek().type == TokenType.COMMA:
                # MySQL 风格 LIMIT offset, count
                self._next()
                stmt.offset = stmt.limit
                stmt.limit = self._parse_limit_value()
            elif self._is_kw("OFFSET"):
                self._next()
                stmt.offset = self._parse_limit_value()
        elif self._is_kw("OFFSET"):
            self._next()
            stmt.offset = self._parse_limit_value()
            if self._is_kw("ROWS"):
                self._next()
            if self._is_kw("FETCH"):
                self._next()
                if self._is_kw("NEXT") or self._is_kw("FIRST"):
                    self._next()
                stmt.limit = self._parse_limit_value()
                self._expect_kw("ROWS")
                if not (self._is_kw("ONLY") and self._next()):
                    raise self._error("FETCH 子句必须以 ONLY 结尾")

    def _parse_limit_value(self):
        tok = self._peek()
        negative = False
        if tok.type == TokenType.OP and tok.value == "-":
            self._next()
            negative = True
            tok = self._peek()
        if tok.type == TokenType.NUMBER:
            self._next()
            value = -int(tok.value) if negative else int(tok.value)
            if value < 0:
                raise SqlParseError("LIMIT/OFFSET 不能为负数", position=tok.position)
            return Literal(value=value, kind="number")
        if tok.type == TokenType.PARAM:
            self._next()
            return self._make_placeholder()
        raise self._error("LIMIT/OFFSET 需要非负整数或占位符")

    # ---------- 表达式（优先级递增） ----------

    def _parse_expr(self):
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while self._is_kw("OR"):
            self._next()
            left = BinaryOp(op="OR", left=left, right=self._parse_and())
        return left

    def _parse_and(self):
        left = self._parse_not()
        while self._is_kw("AND"):
            self._next()
            left = BinaryOp(op="AND", left=left, right=self._parse_not())
        return left

    def _parse_not(self):
        if self._is_kw("NOT"):
            self._next()
            return UnaryOp(op="NOT", operand=self._parse_not())
        return self._parse_comparison()

    def _parse_comparison(self):
        left = self._parse_concat()
        tok = self._peek()
        if tok.type == TokenType.OP and tok.value in ("=", "<", ">", "<=", ">=", "<>", "!="):
            self._next()
            op = "<>" if tok.value == "!=" else tok.value
            return BinaryOp(op=op, left=left, right=self._parse_concat())
        return left

    def _parse_concat(self):
        left = self._parse_additive()
        if self._peek().type == TokenType.OP and self._peek().value == "||":
            parts = [left]
            while self._peek().type == TokenType.OP and self._peek().value == "||":
                self._next()
                parts.append(self._parse_additive())
            return Concat(parts=parts)
        return left

    def _parse_additive(self):
        left = self._parse_multiplicative()
        while self._peek().type == TokenType.OP and self._peek().value in ("+", "-"):
            op = self._next().value
            right = self._parse_multiplicative()
            if isinstance(right, Interval):
                # x +/- INTERVAL n unit -> DateAdd
                amount = right.value
                if op == "-":
                    amount = UnaryOp(op="-", operand=amount)
                left = DateAdd(base=left, amount=amount, unit=right.unit)
            else:
                left = BinaryOp(op=op, left=left, right=right)
        return left

    def _parse_multiplicative(self):
        left = self._parse_unary()
        while self._peek().type == TokenType.OP and self._peek().value in ("*", "/"):
            op = self._next().value
            left = BinaryOp(op=op, left=left, right=self._parse_unary())
        return left

    def _parse_unary(self):
        tok = self._peek()
        if tok.type == TokenType.OP and tok.value == "-":
            self._next()
            return UnaryOp(op="-", operand=self._parse_unary())
        return self._parse_primary()

    def _parse_primary(self):
        tok = self._peek()
        if tok.type == TokenType.NUMBER:
            self._next()
            value = float(tok.value) if "." in tok.value else int(tok.value)
            return Literal(value=value, kind="number")
        if tok.type == TokenType.STRING:
            self._next()
            return Literal(value=tok.value, kind="string")
        if tok.type == TokenType.PARAM:
            self._next()
            return self._make_placeholder()
        if tok.type == TokenType.LPAREN:
            self._next()
            expr = self._parse_expr()
            self._expect(TokenType.RPAREN, "右括号 )")
            return expr
        if tok.type in (TokenType.IDENT, TokenType.QIDENT):
            return self._parse_ident_or_func()
        raise self._error(f"意外的记号 {tok.value!r}")

    def _make_placeholder(self) -> Placeholder:
        ph = Placeholder(index=self._param_count)
        self._param_count += 1
        return ph

    def _parse_ident_or_func(self):
        tok = self._next()
        upper = tok.value.upper()
        if tok.type == TokenType.IDENT:
            if upper == "TRUE":
                return BooleanLiteral(value=True)
            if upper == "FALSE":
                return BooleanLiteral(value=False)
            if upper == "NULL":
                return Literal(value=None, kind="null")
            if upper == "INTERVAL":
                return self._parse_interval()
            if self._peek().type == TokenType.LPAREN:
                return self._parse_function(tok)
        # 普通标识符，可能限定 a.b.c
        parts = [tok.value]
        quoted = tok.type == TokenType.QIDENT
        while self._peek().type == TokenType.DOT:
            self._next()
            nxt = self._peek()
            if nxt.type not in (TokenType.IDENT, TokenType.QIDENT):
                raise self._error("限定标识符中 . 之后必须是标识符")
            self._next()
            parts.append(nxt.value)
            quoted = quoted or nxt.type == TokenType.QIDENT
        if len(parts) == 1:
            return Identifier(name=parts[0], quoted=quoted)
        return QualifiedName(parts=parts, quoted=quoted)

    def _parse_interval(self) -> Interval:
        tok = self._peek()
        if tok.type == TokenType.NUMBER:
            self._next()
            value = Literal(value=int(tok.value), kind="number")
            unit_tok = self._expect(TokenType.IDENT, "时间单位")
            unit = unit_tok.value.lower()
        elif tok.type == TokenType.STRING:
            # PostgreSQL 风格 INTERVAL '1 day'
            self._next()
            pieces = tok.value.strip().split()
            if len(pieces) != 2 or not pieces[0].lstrip("-").isdigit():
                raise SqlParseError(
                    f"INTERVAL 字面量格式应为 '<整数> <单位>'，实际为 {tok.value!r}",
                    position=tok.position)
            value = Literal(value=int(pieces[0]), kind="number")
            unit = pieces[1].lower()
        elif tok.type == TokenType.PARAM:
            self._next()
            value = self._make_placeholder()
            unit_tok = self._expect(TokenType.IDENT, "时间单位")
            unit = unit_tok.value.lower()
        else:
            raise self._error("INTERVAL 后需要数字、字符串或占位符")
        if unit.upper() not in _INTERVAL_UNITS:
            raise SqlParseError(f"不支持的时间单位 {unit!r}",
                                position=tok.position)
        return Interval(value=value, unit=unit.rstrip("s"))

    def _parse_function(self, name_tok: Token):
        raw = name_tok.value.lower()
        self._expect(TokenType.LPAREN, "左括号 (")
        args = []
        if self._peek().type != TokenType.RPAREN:
            args.append(self._parse_func_arg(raw, 0))
            idx = 1
            while self._peek().type == TokenType.COMMA:
                self._next()
                args.append(self._parse_func_arg(raw, idx))
                idx += 1
        self._expect(TokenType.RPAREN, "右括号 )")

        if raw == "concat":
            if len(args) < 2:
                raise SqlParseError("CONCAT 至少需要两个参数",
                                    position=name_tok.position)
            return Concat(parts=args)
        if raw == "datetime":
            # SQLite 风格 datetime(x, '+1 day')
            return self._sqlite_datetime(args, name_tok)
        canon = _FUNC_CANON.get(raw)
        if canon == "date_add":
            # DATE_ADD(x, INTERVAL n unit) 或 DATEADD(unit, n, x)
            return self._make_date_add(args, name_tok, sign=1)
        if canon == "date_sub":
            return self._make_date_add(args, name_tok, sign=-1)
        if canon is None:
            raise SqlParseError(f"未知函数 {name_tok.value!r}",
                                position=name_tok.position)
        return FunctionCall(name=canon, args=args)

    def _parse_func_arg(self, func: str, idx: int):
        return self._parse_expr()

    def _make_date_add(self, args, name_tok: Token, sign: int):
        if len(args) == 2 and isinstance(args[1], Interval):
            # DATE_ADD(x, INTERVAL n unit)
            amount = args[1].value
            if sign < 0:
                amount = UnaryOp(op="-", operand=amount)
            return DateAdd(base=args[0], amount=amount, unit=args[1].unit)
        if len(args) == 3:
            # DATEADD(unit, n, x)
            unit_node = args[0]
            if not isinstance(unit_node, Identifier):
                raise SqlParseError("DATEADD 第一个参数必须是时间单位标识符",
                                    position=name_tok.position)
            unit = unit_node.name.lower().rstrip("s")
            if unit.upper() not in _INTERVAL_UNITS:
                raise SqlParseError(f"不支持的时间单位 {unit!r}",
                                    position=name_tok.position)
            amount = args[1]
            if sign < 0:
                amount = UnaryOp(op="-", operand=amount)
            return DateAdd(base=args[2], amount=amount, unit=unit)
        raise SqlParseError("DATE_ADD/DATE_SUB 参数形式不正确",
                            position=name_tok.position)

    def _sqlite_datetime(self, args, name_tok: Token):
        if (len(args) == 2 and isinstance(args[1], Literal)
                and args[1].kind == "string"):
            text = args[1].value.strip()
            sign = 1
            if text.startswith("+"):
                text = text[1:]
            elif text.startswith("-"):
                sign = -1
                text = text[1:]
            pieces = text.split()
            if len(pieces) == 2 and pieces[0].isdigit() \
                    and pieces[1].rstrip("s").upper() in _INTERVAL_UNITS:
                amount = Literal(value=sign * int(pieces[0]), kind="number")
                return DateAdd(base=args[0], amount=amount,
                               unit=pieces[1].rstrip("s").lower())
        raise SqlParseError("datetime() 仅支持 datetime(x, '+/-n unit') 形式",
                            position=name_tok.position)


def parse(sql: str) -> Select:
    if not sql or not sql.strip():
        raise SqlParseError("输入为空", position=0)
    tokens = tokenize(sql)
    return Parser(tokens).parse_select()
