"""方言规则定义。

每个方言是一条带版本号的规则记录（Dialect），描述：
- 标识符引用字符
- 参数占位符风格
- 是否原生支持布尔字面量
- 字符串拼接方式
- 分页语法风格
- 日期时间运算风格
- 函数重写规则表（重命名 / 模板组合 / 明确不支持）

新增方言只需向 registry 注册新的 Dialect，无需改动转译核心。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping, Tuple

# ---------------------------------------------------------------------------
# 函数重写规则
# ---------------------------------------------------------------------------

# 规则类型
RENAME = "rename"          # 直接改名，参数原样传递
TEMPLATE = "template"      # 模板组合，{0} {1} ... 引用渲染后的参数
UNSUPPORTED = "unsupported"  # 目标方言无法等价表达，必须报错


@dataclass(frozen=True)
class FunctionRule:
    kind: str
    value: str = ""      # RENAME 的新名字或 TEMPLATE 的模板串
    reason: str = ""     # UNSUPPORTED 的原因说明

    @staticmethod
    def rename(new_name: str) -> "FunctionRule":
        return FunctionRule(RENAME, value=new_name)

    @staticmethod
    def template(sql: str) -> "FunctionRule":
        return FunctionRule(TEMPLATE, value=sql)

    @staticmethod
    def unsupported(reason: str) -> "FunctionRule":
        return FunctionRule(UNSUPPORTED, reason=reason)


# ---------------------------------------------------------------------------
# 方言描述
# ---------------------------------------------------------------------------

# 占位符风格
PH_QMARK = "qmark"      # ?
PH_NUMERIC = "numeric"  # $1, $2, ...
PH_FORMAT = "format"    # %s
PH_NAMED = "named"      # @p1, @p2, ...

# 字符串拼接风格
CONCAT_OPERATOR = "operator"  # a || b
CONCAT_FUNCTION = "function"  # CONCAT(a, b)
CONCAT_PLUS = "plus"          # a + b（NULL 传播语义与 || 一致时方可使用）

# 分页风格
PAGE_LIMIT_OFFSET = "limit_offset"  # LIMIT n OFFSET m
PAGE_TOP = "top"                    # SELECT TOP n / OFFSET ... FETCH

# 日期运算风格
DATE_INTERVAL = "interval"        # expr + INTERVAL '1 day'
DATE_FUNC = "date_func"           # DATE_ADD(expr, INTERVAL 1 DAY)
DATE_DATEADD = "dateadd"          # DATEADD(day, 1, expr)
DATE_MODIFIER = "date_modifier"   # datetime(expr, '+1 day')


@dataclass(frozen=True)
class Dialect:
    name: str
    version: str
    quote_open: str
    quote_close: str
    placeholder: str
    native_boolean: bool
    concat_style: str
    pagination: str
    date_arith: str
    function_rules: Mapping[str, FunctionRule] = field(default_factory=dict)

    def __post_init__(self) -> None:
        # 规则表固化，避免运行期被意外修改导致结果不稳定
        object.__setattr__(self, "function_rules",
                           MappingProxyType(dict(self.function_rules)))

    def cache_key(self) -> Tuple[str, str]:
        return (self.name, self.version)


# ---------------------------------------------------------------------------
# 源侧函数名归一：各方言写法 -> 规范名
# ---------------------------------------------------------------------------

CANONICAL_ALIASES: Mapping[str, str] = MappingProxyType({
    "NOW": "CURRENT_TIMESTAMP",
    "GETDATE": "CURRENT_TIMESTAMP",
    "SYSDATE": "CURRENT_TIMESTAMP",
    "IFNULL": "COALESCE",
    "ISNULL": "COALESCE",
    "NVL": "COALESCE",
    "LEN": "LENGTH",
    "SUBSTR": "SUBSTRING",
})

# 所有目标方言都可直接透传的规范函数
PASSTHROUGH_FUNCTIONS = frozenset({
    "COALESCE", "UPPER", "LOWER", "TRIM", "ABS", "ROUND",
    "COUNT", "SUM", "AVG", "MIN", "MAX", "LENGTH", "SUBSTRING",
    "CURRENT_TIMESTAMP",
})


# ---------------------------------------------------------------------------
# 内置方言
# ---------------------------------------------------------------------------

MYSQL = Dialect(
    name="mysql",
    version="1.0.0",
    quote_open="`",
    quote_close="`",
    placeholder=PH_QMARK,
    native_boolean=False,       # TRUE/FALSE 是 1/0 的别名，统一输出 1/0
    concat_style=CONCAT_FUNCTION,
    pagination=PAGE_LIMIT_OFFSET,
    date_arith=DATE_FUNC,
    function_rules={
        "GROUP_CONCAT": FunctionRule.rename("GROUP_CONCAT"),
        "REGEXP_REPLACE": FunctionRule.rename("REGEXP_REPLACE"),
        "ARRAY_AGG": FunctionRule.unsupported(
            "mysql has no array type or ARRAY_AGG aggregate"),
    },
)

POSTGRES = Dialect(
    name="postgres",
    version="1.0.0",
    quote_open='"',
    quote_close='"',
    placeholder=PH_NUMERIC,
    native_boolean=True,
    concat_style=CONCAT_OPERATOR,
    pagination=PAGE_LIMIT_OFFSET,
    date_arith=DATE_INTERVAL,
    function_rules={
        "GROUP_CONCAT": FunctionRule.rename("STRING_AGG"),
        "REGEXP_REPLACE": FunctionRule.rename("REGEXP_REPLACE"),
        "ARRAY_AGG": FunctionRule.rename("ARRAY_AGG"),
    },
)

SQLITE = Dialect(
    name="sqlite",
    version="1.0.0",
    quote_open='"',
    quote_close='"',
    placeholder=PH_QMARK,
    native_boolean=True,
    concat_style=CONCAT_OPERATOR,
    pagination=PAGE_LIMIT_OFFSET,
    date_arith=DATE_MODIFIER,
    function_rules={
        "GROUP_CONCAT": FunctionRule.rename("GROUP_CONCAT"),
        "SUBSTRING": FunctionRule.rename("SUBSTR"),
        "REGEXP_REPLACE": FunctionRule.unsupported(
            "sqlite has no built-in REGEXP_REPLACE function"),
        "ARRAY_AGG": FunctionRule.unsupported(
            "sqlite has no array type or ARRAY_AGG aggregate"),
    },
)

MSSQL = Dialect(
    name="mssql",
    version="1.0.0",
    quote_open="[",
    quote_close="]",
    placeholder=PH_NAMED,
    native_boolean=False,
    concat_style=CONCAT_PLUS,
    pagination=PAGE_TOP,
    date_arith=DATE_DATEADD,
    function_rules={
        "LENGTH": FunctionRule.rename("LEN"),
        "GROUP_CONCAT": FunctionRule.rename("STRING_AGG"),
        "REGEXP_REPLACE": FunctionRule.unsupported(
            "mssql has no built-in REGEXP_REPLACE function"),
        "ARRAY_AGG": FunctionRule.unsupported(
            "mssql has no ARRAY_AGG aggregate"),
    },
)

BUILTIN_DIALECTS: Tuple[Dialect, ...] = (MYSQL, POSTGRES, SQLITE, MSSQL)
