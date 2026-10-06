# SQL Dialect Transpiler

基于语法结构的跨方言 SQL 转译器：把来自不同来源的 SELECT 语句统一转译到
目标方言执行。转译在 AST 层面进行（解析 → 归一 → 按方言规则生成），
不做关键字级字符串替换。

## 支持的方言

| 方言 | 标识符引用 | 占位符 | 布尔字面量 | 字符串拼接 | 分页 | 日期运算 |
|------|-----------|--------|-----------|-----------|------|----------|
| mysql | `` `x` `` | `?` | `1`/`0` | `CONCAT(a, b)` | `LIMIT n OFFSET m` | `DATE_ADD(x, INTERVAL 1 DAY)` |
| postgres | `"x"` | `$1, $2` | `TRUE`/`FALSE` | `a \|\| b` | `LIMIT n OFFSET m` | `x + INTERVAL '1 day'` |
| sqlite | `"x"` | `?` | `TRUE`/`FALSE` | `a \|\| b` | `LIMIT n OFFSET m` | `datetime(x, '+1 day')` |
| mssql | `[x]` | `@p1, @p2` | `1`/`0` | `a + b` | `TOP n` / `OFFSET … FETCH` | `DATEADD(day, 1, x)` |

支持的语句范围：`SELECT`（列与别名、`FROM`、`WHERE`、`ORDER BY`、
`LIMIT/OFFSET`、`LIMIT a,b`、`TOP n`、`OFFSET/FETCH`），表达式包括
字面量、占位符（`?`、`$n`、`%s`、`:name`）、函数调用、`CASE`、
`INTERVAL`、算术/比较/逻辑/拼接运算。

## 转译语义

- **标识符**：未加引号的标识符统一折叠为小写（输入书写风格不影响结果）；
  加引号的标识符保留原始大小写，并改用目标方言的引用符。
- **占位符**：按出现顺序统一编号，输出为目标方言风格；命名占位符
  （`:x`）转为位置占位符。
- **布尔字面量**：目标方言无原生布尔时输出 `1`/`0`。
- **函数归一**：`NOW`/`GETDATE` → `CURRENT_TIMESTAMP`，
  `IFNULL`/`ISNULL`/`NVL` → `COALESCE`，`LEN` → `LENGTH`，
  `SUBSTR` → `SUBSTRING`，`DATEADD(unit, n, x)` → `x + INTERVAL n unit`。
- **方言专有写法重写**：`IF(c,a,b)` → `CASE WHEN … END`；
  `GROUP_CONCAT` ↔ `STRING_AGG`；`INTERVAL n WEEK` 在 sqlite 下展开为
  `7*n` 天。无法等价表达时（如 `ARRAY_AGG`、`REGEXP_REPLACE` 在无对应
  实现的方言中）抛出 `UnsupportedFeatureError`，不生成语义错误的语句。
- **分页边界**：`OFFSET 0` 省略；`LIMIT` 极大值原样透传；负数
  `LIMIT`/`OFFSET` 在解析期即报 `SqlSyntaxError`；mssql 无偏移时用
  `TOP n`，有偏移时用 `OFFSET/FETCH`（缺 `ORDER BY` 时补
  `ORDER BY (SELECT NULL)`）。

## 错误分类

所有错误继承 `TranspileError`，通过 `category` 区分：

| category | 含义 | HTTP 状态码 |
|----------|------|------------|
| `syntax_error` | 输入 SQL 语法错误，带字符位置 | 400 |
| `unknown_dialect` | 引用了未注册的方言，列出可用方言 | 404 |
| `unsupported_feature` | 目标方言不支持该特性，附原因 | 422 |
| `roundtrip_mismatch` | 往返校验结构无法对齐，附差异说明 | 422 |

## 用法

```python
from transpiler import Transpiler

t = Transpiler()
t.transpile("SELECT name || 'x' FROM users WHERE id = ? LIMIT 10",
            source="postgres", target="mysql").sql
# => SELECT CONCAT(name, 'x') FROM users WHERE id = ? LIMIT 10

# 往返语义校验：转到目标方言再转回，关键结构必须对齐
report = t.validate_roundtrip(sql, "mysql", "postgres")
report.ok, report.diffs

# 转译并强制校验，无法对齐时抛 RoundtripMismatchError
t.transpile_checked(sql, "mysql", "postgres")
```

HTTP 入口（`main.py`）：

- `GET /dialects` — 已注册方言及规则版本
- `POST /transpile` — `{"sql", "source", "target", "validate_roundtrip?"}`

## 扩展新方言

新增方言无需改动转译核心，只需注册一条带版本的规则记录：

```python
from transpiler import Dialect, DialectRegistry, FunctionRule, Transpiler
from transpiler.dialects import (CONCAT_OPERATOR, DATE_INTERVAL,
                                 PAGE_LIMIT_OFFSET, PH_QMARK)

oracle = Dialect(
    name="oracle", version="1.0.0",
    quote_open='"', quote_close='"', placeholder=PH_NAMED,
    native_boolean=False, concat_style=CONCAT_OPERATOR,
    pagination=PAGE_LIMIT_OFFSET, date_arith=DATE_INTERVAL,
    function_rules={"LENGTH": FunctionRule.rename("LENGTH")},
)
reg = DialectRegistry()
reg.register(oracle)
t = Transpiler(reg)
```

同名同版本的重复注册必须内容一致（幂等），同名新版本视为规则升级。

## 缓存与并发

`Transpiler` 线程安全，内置 LRU 缓存。缓存键为
`(SQL 文本, (源方言, 版本), (目标方言, 版本))`：方言组合或规则版本
任一变化都会产生新键，规则升级后旧缓存自然失效。同一输入在任意注册
顺序、任意并发下结果一致。

## 测试

```bash
python -m pytest tests/ -q
```

覆盖：多方言转译、书写风格稳定性、分页/日期/拼接边界、错误分类、
往返校验、缓存失效、并发一致性、注册顺序无关性、HTTP 接口。
