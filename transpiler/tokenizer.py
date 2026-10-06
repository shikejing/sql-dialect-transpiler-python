"""SQL 词法分析：把输入切成 token 流。"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import SqlParseError


class TokenType(Enum):
    IDENT = "ident"
    QIDENT = "qident"      # 带引号的标识符（双引号/反引号/方括号）
    NUMBER = "number"
    STRING = "string"
    PARAM = "param"        # 占位符 ? %s $1 :1 @p1
    OP = "op"
    LPAREN = "lparen"
    RPAREN = "rparen"
    COMMA = "comma"
    DOT = "dot"
    EOF = "eof"


@dataclass
class Token:
    type: TokenType
    value: str
    position: int


_OPERATORS = ("||", "<=", ">=", "<>", "!=", "=", "<", ">", "+", "-", "*", "/")


def tokenize(sql: str) -> list[Token]:
    tokens: list[Token] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        # 空白与注释
        if ch.isspace():
            i += 1
            continue
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        # 字符串字面量
        if ch == "'":
            j = i + 1
            buf = []
            while j < n:
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    break
                buf.append(sql[j])
                j += 1
            if j >= n:
                raise SqlParseError("未闭合的字符串字面量", position=i)
            tokens.append(Token(TokenType.STRING, "".join(buf), i))
            i = j + 1
            continue
        # 带引号标识符
        if ch in ('"', "`"):
            close = ch
            j = sql.find(close, i + 1)
            if j < 0:
                raise SqlParseError("未闭合的引用标识符", position=i)
            tokens.append(Token(TokenType.QIDENT, sql[i + 1:j], i))
            i = j + 1
            continue
        if ch == "[":
            j = sql.find("]", i + 1)
            if j < 0:
                raise SqlParseError("未闭合的引用标识符", position=i)
            tokens.append(Token(TokenType.QIDENT, sql[i + 1:j], i))
            i = j + 1
            continue
        # 数字
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            while j < n and (sql[j].isdigit() or sql[j] == "."):
                j += 1
            tokens.append(Token(TokenType.NUMBER, sql[i:j], i))
            i = j
            continue
        # 占位符
        if ch == "?":
            tokens.append(Token(TokenType.PARAM, "?", i))
            i += 1
            continue
        if sql.startswith("%s", i):
            tokens.append(Token(TokenType.PARAM, "%s", i))
            i += 2
            continue
        if ch == "$" and i + 1 < n and sql[i + 1].isdigit():
            j = i + 1
            while j < n and sql[j].isdigit():
                j += 1
            tokens.append(Token(TokenType.PARAM, sql[i:j], i))
            i = j
            continue
        if ch == "@" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "p"):
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            tokens.append(Token(TokenType.PARAM, sql[i:j], i))
            i = j
            continue
        if ch == ":" and i + 1 < n and sql[i + 1].isdigit():
            j = i + 1
            while j < n and sql[j].isdigit():
                j += 1
            tokens.append(Token(TokenType.PARAM, sql[i:j], i))
            i = j
            continue
        # 标识符 / 关键字
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            tokens.append(Token(TokenType.IDENT, sql[i:j], i))
            i = j
            continue
        # 标点与运算符
        if ch == "(":
            tokens.append(Token(TokenType.LPAREN, ch, i)); i += 1; continue
        if ch == ")":
            tokens.append(Token(TokenType.RPAREN, ch, i)); i += 1; continue
        if ch == ",":
            tokens.append(Token(TokenType.COMMA, ch, i)); i += 1; continue
        if ch == ".":
            tokens.append(Token(TokenType.DOT, ch, i)); i += 1; continue
        matched = False
        for op in _OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token(TokenType.OP, op, i))
                i += len(op)
                matched = True
                break
        if matched:
            continue
        raise SqlParseError(f"无法识别的字符 {ch!r}", position=i)
    tokens.append(Token(TokenType.EOF, "", n))
    return tokens
