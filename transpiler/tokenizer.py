"""SQL 词法分析器。

产出带位置信息的 Token 流，供解析器使用。
识别：标识符（含各方言引用形式）、字符串、数字、占位符、运算符、标点。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .errors import SqlSyntaxError

# Token 类别
KEYWORD = "keyword"
IDENT = "ident"          # 裸标识符
QIDENT = "qident"        # 带引号标识符
STRING = "string"
NUMBER = "number"
PLACEHOLDER = "placeholder"
OP = "op"
PUNCT = "punct"
EOF = "eof"

KEYWORDS = {
    "SELECT", "FROM", "WHERE", "AND", "OR", "NOT", "AS", "ORDER", "BY",
    "ASC", "DESC", "LIMIT", "OFFSET", "FETCH", "FIRST", "NEXT", "ROWS",
    "ONLY", "TOP", "CASE", "WHEN", "THEN", "ELSE", "END", "TRUE", "FALSE",
    "NULL", "INTERVAL", "LIKE", "IN", "IS", "BETWEEN", "DISTINCT",
}

# 多字符运算符优先匹配
_OPERATORS = ("<=", ">=", "<>", "!=", "||", "=", "<", ">", "+", "-", "*", "/", "%")
_PUNCT = ("(", ")", ",", ".")

# 各方言的标识符引用字符（解析阶段统一接受，规范化在 AST 层完成）
_QUOTE_PAIRS = {'"': '"', '`': '`', '[': ']'}


@dataclass(frozen=True)
class Token:
    kind: str
    text: str          # 原文（标识符/字符串为解码后的值）
    pos: int           # 在源串中的字符偏移
    quoted: bool = False  # 标识符是否带引号


def tokenize(sql: str) -> List[Token]:
    tokens: List[Token] = []
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        # 空白
        if ch.isspace():
            i += 1
            continue
        # 行注释 -- 与块注释 /* */
        if sql.startswith("--", i):
            j = sql.find("\n", i)
            i = n if j < 0 else j + 1
            continue
        if sql.startswith("/*", i):
            j = sql.find("*/", i + 2)
            if j < 0:
                raise SqlSyntaxError("unterminated block comment", position=i)
            i = j + 2
            continue
        # 字符串字面量（单引号，'' 转义）
        if ch == "'":
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise SqlSyntaxError("unterminated string literal", position=i)
                if sql[j] == "'":
                    if j + 1 < n and sql[j + 1] == "'":
                        buf.append("'")
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            tokens.append(Token(STRING, "".join(buf), i))
            i = j
            continue
        # 带引号标识符
        if ch in _QUOTE_PAIRS:
            close = _QUOTE_PAIRS[ch]
            j = i + 1
            buf = []
            while True:
                if j >= n:
                    raise SqlSyntaxError("unterminated quoted identifier", position=i)
                if sql[j] == close:
                    if close != "]" and j + 1 < n and sql[j + 1] == close:
                        buf.append(close)
                        j += 2
                        continue
                    j += 1
                    break
                buf.append(sql[j])
                j += 1
            tokens.append(Token(QIDENT, "".join(buf), i, quoted=True))
            i = j
            continue
        # 数字
        if ch.isdigit() or (ch == "." and i + 1 < n and sql[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (sql[j].isdigit() or (sql[j] == "." and not seen_dot)):
                if sql[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token(NUMBER, sql[i:j], i))
            i = j
            continue
        # 占位符：?  :name  %s  $n
        if ch == "?":
            tokens.append(Token(PLACEHOLDER, "?", i))
            i += 1
            continue
        if ch == "%" and sql.startswith("%s", i):
            tokens.append(Token(PLACEHOLDER, "%s", i))
            i += 2
            continue
        if ch == "$" and i + 1 < n and sql[i + 1].isdigit():
            j = i + 1
            while j < n and sql[j].isdigit():
                j += 1
            tokens.append(Token(PLACEHOLDER, sql[i:j], i))
            i = j
            continue
        if ch == ":" and i + 1 < n and (sql[i + 1].isalpha() or sql[i + 1] == "_"):
            j = i + 1
            while j < n and (sql[j].isalnum() or sql[j] == "_"):
                j += 1
            tokens.append(Token(PLACEHOLDER, sql[i:j], i))
            i = j
            continue
        # 运算符
        matched = False
        for op in _OPERATORS:
            if sql.startswith(op, i):
                tokens.append(Token(OP, op, i))
                i += len(op)
                matched = True
                break
        if matched:
            continue
        # 标点
        if ch in _PUNCT:
            tokens.append(Token(PUNCT, ch, i))
            i += 1
            continue
        # 裸标识符 / 关键字
        if ch.isalpha() or ch == "_":
            j = i
            while j < n and (sql[j].isalnum() or sql[j] in "_$"):
                j += 1
            word = sql[i:j]
            upper = word.upper()
            if upper in KEYWORDS:
                tokens.append(Token(KEYWORD, upper, i))
            else:
                tokens.append(Token(IDENT, word, i))
            i = j
            continue
        raise SqlSyntaxError(f"unexpected character {ch!r}", position=i)
    tokens.append(Token(EOF, "", n))
    return tokens
