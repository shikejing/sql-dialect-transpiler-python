# SQL Dialect Transpiler

基于语法结构（AST）的跨方言 SQL 转译器：把来自不同来源的 SELECT 语句统一转译到目标方言执行。
不依赖关键字替换，所有改写都发生在结构化的中间表示上。

## 支持的方言

| 方言 | 标识符引用 | 占位符 | 布尔字面量 | 分页 | 拼接 | 日期加减 |
|------|-----------|--------|-----------|------|------|----------|
| mysql | `` `x` `` | `%s` | `TRUE/FALSE` | `LIMIT n OFFSET m` | `CONCAT(a,b)` | `DATE_ADD(x, INTERVAL n u)` |
| postgres | `"x"` | `$1, $2…` | `TRUE/FALSE` | `LIMIT n OFFSET m` | `a \|\| b` | `x + INTERVAL 'n u'` |
| sqlite | `"x"` | `?` | `1/0` | `LIMIT n OFFSET m` | `a \|\| b` | `datetime(x, '+n u')` |
| sqlserver | `[x]` | `@p1, @p2…` | `1/0` | `OFFSET m ROWS FETCH NEXT n ROWS ONLY` | `CONCAT(a,b)` | `DATEADD(u, n, x)` |

支持的语句范围：`SELECT ... [FROM ...] [WHERE ...] [LIMIT/OFFSET | OFFSET ... FETCH]`，
表达式覆盖比较、AND/OR/NOT、算术、字符串拼接（`||` / `CONCAT`）、
日期加减（`DATE_ADD`/`DATE_SUB`/`DATEADD`/`datetime()`/`± INTERVAL`）、
以及一组规范函数（`length`、`substring`、`string_agg`、`upper`、`lower`、`coalesce`、`abs`、`now`）。

## 转译语义

- **标识符**：未加引号的标识符按源方言规则折叠大小写（postgres 折叠为小写，其余保留），
  输出时统一使用目标方言的引用符；带引号的标识符保留原始大小写。
  输入的空白与关键字大小写不影响输出。
- **占位符**：按出现顺序重新编号为目标方言样式（`?` / `%s` / `$n` / `@pn`）。
- **布尔字面量**：目标方言无布尔字面量时改写为 `1/0`。
- **分页**：`OFFSET 0` 在 `LIMIT/OFFSET` 方言下省略；sqlserver 下 `LIMIT n` 改写为
  `OFFSET 0 ROWS FETCH NEXT n ROWS ONLY`；只有 OFFSET 没有 LIMIT 时使用方言哨兵
  （mysql `18446744073709551615`、sqlite `-1`、postgres `ALL`）。
  负数 LIMIT/OFFSET 一律拒绝（解析错误）。
- **日期加减**：负间隔折叠为减法语义（`DATE_SUB` → `x - INTERVAL 'n u'`）。
  sqlite 只支持常量间隔，动态间隔（占位符）会报 `unsupported_feature`。
- **函数**：按规范名映射到目标方言函数（如 `length` → sqlserver `LEN`）。
  目标方言无等价实现时报 `unsupported_feature`，绝不生成语义存疑的语句。

## 错误分类

所有错误都是 `TranspileError` 的子类，携带 `kind`、`message`、`position`：

| kind | 含义 | HTTP 状态码 |
|------|------|------------|
| `parse` | 输入语法错误（含位置） | 422 |
| `unknown_dialect` | 引用了未注册的方言 | 400 |
| `unsupported_feature` | 目标方言不支持该特性 | 422 |

## 使用方式

库调用：

```python
from transpiler import Transpiler
from transpiler.builtins import register_builtins

register_builtins()
tp = Transpiler()
tp.transpile("SELECT a FROM t WHERE x = ? LIMIT 5", "sqlite", "postgres").sql
# 'SELECT "a" FROM "t" WHERE "x" = $1 LIMIT 5'

report = tp.validate_roundtrip("SELECT a FROM t LIMIT 5", "mysql", "postgres")
report.ok, report.differences
```

HTTP 服务（`uv run python main.py` 或 `uvicorn main:app`）：

- `POST /transpile` `{sql, source, target}` → `{sql, source, target, cached}`
- `POST /validate` `{sql, source, target}` → 往返校验报告
- `GET /dialects` → 已注册方言及规则版本

## 方言扩展

新增方言无需改动转译核心，注册一条带版本的规则即可：

```python
from transpiler import DialectRules, register_dialect

register_dialect(DialectRules(name="mydb", version="1.0.0", ...))
```

同名方言保留最高版本，与注册顺序无关；版本号变化会使相关缓存自动失效。

## 缓存与并发

`Transpiler` 线程安全，可被多线程/多请求共享。缓存键覆盖
`(规范化SQL, 源方言, 目标方言, 源规则版本, 目标规则版本, 注册代际)`，
任何规则更新都会使旧缓存失效。

## 测试

```bash
uv run pytest
```

覆盖：多方言转译、错误分类、往返结构对齐、缓存失效、注册顺序无关性与并发转译。
