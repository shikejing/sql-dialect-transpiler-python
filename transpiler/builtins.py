"""内置方言规则：mysql / postgres / sqlite / sqlserver。"""
from __future__ import annotations

from .dialects import DialectRules, register_dialect

BUILTIN_VERSION = "1.0.0"

_COMMON_FUNCS = {"upper": "UPPER", "lower": "LOWER",
                 "coalesce": "COALESCE", "abs": "ABS"}

_MYSQL = DialectRules(
    name="mysql", version=BUILTIN_VERSION,
    ident_quote_open="`", ident_quote_close="`",
    fold_unquoted="preserve",
    placeholder_style="format",
    bool_literals=("TRUE", "FALSE"),
    pagination_style="limit_offset",
    limit_all_token="18446744073709551615",
    concat_style="function",
    date_arith_style="interval_kw",
    function_map={**_COMMON_FUNCS, "string_agg": "GROUP_CONCAT",
                  "length": "LENGTH", "substring": "SUBSTRING", "now": "NOW"},
)

_POSTGRES = DialectRules(
    name="postgres", version=BUILTIN_VERSION,
    ident_quote_open='"', ident_quote_close='"',
    fold_unquoted="lower",
    placeholder_style="numeric_dollar",
    bool_literals=("TRUE", "FALSE"),
    pagination_style="limit_offset",
    limit_all_token="ALL",
    concat_style="operator",
    date_arith_style="interval_op",
    function_map={**_COMMON_FUNCS, "string_agg": "STRING_AGG",
                  "length": "LENGTH", "substring": "SUBSTRING", "now": "NOW"},
)

_SQLITE = DialectRules(
    name="sqlite", version=BUILTIN_VERSION,
    ident_quote_open='"', ident_quote_close='"',
    fold_unquoted="preserve",
    placeholder_style="qmark",
    bool_literals=("1", "0"),
    pagination_style="limit_offset",
    limit_all_token="-1",
    concat_style="operator",
    date_arith_style="datetime_mod",
    # sqlite 无 now() 等价函数，刻意不映射以体现“不支持即报错”
    function_map={**_COMMON_FUNCS, "string_agg": "GROUP_CONCAT",
                  "length": "LENGTH", "substring": "SUBSTR"},
)

_SQLSERVER = DialectRules(
    name="sqlserver", version=BUILTIN_VERSION,
    ident_quote_open="[", ident_quote_close="]",
    fold_unquoted="preserve",
    placeholder_style="named_at",
    bool_literals=("1", "0"),
    pagination_style="offset_fetch",
    concat_style="function",
    date_arith_style="dateadd",
    function_map={**_COMMON_FUNCS, "string_agg": "STRING_AGG",
                  "length": "LEN", "substring": "SUBSTRING", "now": "GETDATE"},
)

_BUILTINS = (_MYSQL, _POSTGRES, _SQLITE, _SQLSERVER)


def register_builtins() -> None:
    for rules in _BUILTINS:
        register_dialect(rules)
