"""多方言转译：引用、大小写、占位符、布尔、拼接、分页、日期运算、函数重写。"""

import pytest

from transpiler import Transpiler
from transpiler.errors import SqlSyntaxError


@pytest.fixture(scope="module")
def t():
    return Transpiler()


# ---------------------------------------------------------------------------
# 标识符引用与大小写折叠
# ---------------------------------------------------------------------------

def test_identifier_quoting_per_dialect(t):
    sql = 'SELECT "UserName", `age` FROM "Users"'
    assert t.transpile(sql, "postgres", "mysql").sql == \
        "SELECT `UserName`, `age` FROM `Users`"
    assert t.transpile(sql, "mysql", "postgres").sql == \
        'SELECT "UserName", "age" FROM "Users"'
    assert t.transpile(sql, "postgres", "mssql").sql == \
        "SELECT [UserName], [age] FROM [Users]"


def test_unquoted_identifiers_folded_and_stable(t):
    a = t.transpile("SELECT Name FROM Users", "mysql", "postgres").sql
    b = t.transpile("select NAME from USERS", "mysql", "postgres").sql
    c = t.transpile("  SeLeCt  name  FROM  users ", "mysql", "postgres").sql
    assert a == b == c == "SELECT name FROM users"


def test_quoted_identifier_case_preserved(t):
    out = t.transpile('SELECT "Name" FROM "Users"', "postgres", "mysql").sql
    assert out == "SELECT `Name` FROM `Users`"


# ---------------------------------------------------------------------------
# 占位符与布尔字面量
# ---------------------------------------------------------------------------

def test_placeholders_renumbered_per_dialect(t):
    sql = "SELECT * FROM t WHERE a = ? AND b = ? AND c = ?"
    assert t.transpile(sql, "mysql", "postgres").sql.endswith("a = $1 AND b = $2 AND c = $3")
    assert t.transpile(sql, "mysql", "mssql").sql.endswith("a = @p1 AND b = @p2 AND c = @p3")
    pg = "SELECT * FROM t WHERE a = $1 AND b = $2"
    assert t.transpile(pg, "postgres", "mysql").sql.endswith("a = ? AND b = ?")


def test_named_placeholders_become_positional(t):
    out = t.transpile("SELECT * FROM t WHERE a = :x AND b = :y", "postgres", "mysql").sql
    assert out.endswith("a = ? AND b = ?")


def test_boolean_literals(t):
    sql = "SELECT * FROM t WHERE active = TRUE AND deleted = FALSE"
    assert "active = TRUE AND deleted = FALSE" in t.transpile(sql, "mysql", "postgres").sql
    assert "active = 1 AND deleted = 0" in t.transpile(sql, "postgres", "mysql").sql
    assert "active = 1 AND deleted = 0" in t.transpile(sql, "postgres", "mssql").sql


# ---------------------------------------------------------------------------
# 字符串拼接
# ---------------------------------------------------------------------------

def test_concat_styles(t):
    sql = "SELECT first || ' ' || last FROM users"
    assert t.transpile(sql, "postgres", "mysql").sql == \
        "SELECT CONCAT(first, ' ', last) FROM users"
    assert t.transpile(sql, "postgres", "mssql").sql == \
        "SELECT first + ' ' + last FROM users"
    back = t.transpile("SELECT CONCAT(first, ' ', last) FROM users", "mysql", "postgres").sql
    assert back == "SELECT first || ' ' || last FROM users"


# ---------------------------------------------------------------------------
# 分页与边界
# ---------------------------------------------------------------------------

def test_pagination_limit_offset(t):
    sql = "SELECT a FROM t LIMIT 10 OFFSET 5"
    assert t.transpile(sql, "mysql", "postgres").sql.endswith("LIMIT 10 OFFSET 5")
    assert t.transpile(sql, "mysql", "mssql").sql == \
        "SELECT a FROM t ORDER BY (SELECT NULL) OFFSET 5 ROWS FETCH NEXT 10 ROWS ONLY"


def test_pagination_offset_zero_omitted(t):
    out = t.transpile("SELECT a FROM t LIMIT 10 OFFSET 0", "mysql", "postgres").sql
    assert out == "SELECT a FROM t LIMIT 10"
    out_ms = t.transpile("SELECT a FROM t LIMIT 10 OFFSET 0", "mysql", "mssql").sql
    assert out_ms == "SELECT TOP 10 a FROM t"


def test_pagination_mysql_comma_form(t):
    out = t.transpile("SELECT a FROM t LIMIT 5, 10", "mysql", "postgres").sql
    assert out == "SELECT a FROM t LIMIT 10 OFFSET 5"


def test_pagination_top_and_fetch_parsed(t):
    assert t.transpile("SELECT TOP 3 a FROM t", "mssql", "postgres").sql == \
        "SELECT a FROM t LIMIT 3"
    assert t.transpile("SELECT a FROM t OFFSET 2 ROWS FETCH NEXT 5 ROWS ONLY",
                       "mssql", "mysql").sql == "SELECT a FROM t LIMIT 5 OFFSET 2"


def test_pagination_huge_limit_passthrough(t):
    out = t.transpile("SELECT a FROM t LIMIT 9223372036854775807", "mysql", "postgres").sql
    assert out.endswith("LIMIT 9223372036854775807")


def test_pagination_negative_limit_rejected(t):
    with pytest.raises(SqlSyntaxError, match="LIMIT must not be negative"):
        t.transpile("SELECT a FROM t LIMIT -1", "mysql", "postgres")
    with pytest.raises(SqlSyntaxError, match="OFFSET must not be negative"):
        t.transpile("SELECT a FROM t LIMIT 1 OFFSET -5", "mysql", "postgres")


# ---------------------------------------------------------------------------
# 日期时间运算
# ---------------------------------------------------------------------------

def test_date_arith_interval(t):
    sql = "SELECT created_at + INTERVAL 1 DAY FROM t"
    assert t.transpile(sql, "mysql", "postgres").sql == \
        "SELECT created_at + INTERVAL '1 day' FROM t"
    assert t.transpile(sql, "mysql", "mssql").sql == \
        "SELECT DATEADD(day, 1, created_at) FROM t"
    assert t.transpile(sql, "mysql", "sqlite").sql == \
        "SELECT datetime(created_at, '+1 days') FROM t"


def test_date_arith_reverse_and_pg_literal(t):
    assert t.transpile("SELECT created_at - INTERVAL '2 hours' FROM t",
                       "postgres", "mysql").sql == \
        "SELECT DATE_SUB(created_at, INTERVAL 2 HOUR) FROM t"


def test_dateadd_canonicalized(t):
    out = t.transpile("SELECT DATEADD(day, 3, created_at) FROM t", "mssql", "postgres").sql
    assert out == "SELECT created_at + INTERVAL '3 day' FROM t"


def test_week_interval_to_sqlite_expanded_to_days(t):
    # sqlite 修饰符不支持 WEEK，确定性地展开为 7 倍天数
    out = t.transpile("SELECT created_at + INTERVAL 2 WEEK FROM t", "mysql", "sqlite").sql
    assert out == "SELECT datetime(created_at, '+14 days') FROM t"


# ---------------------------------------------------------------------------
# 函数重写
# ---------------------------------------------------------------------------

def test_function_renames(t):
    assert t.transpile("SELECT LENGTH(name) FROM t", "mysql", "mssql").sql == \
        "SELECT LEN(name) FROM t"
    assert t.transpile("SELECT LEN(name) FROM t", "mssql", "mysql").sql == \
        "SELECT LENGTH(name) FROM t"
    assert t.transpile("SELECT SUBSTRING(name, 1, 2) FROM t", "mysql", "sqlite").sql == \
        "SELECT SUBSTR(name, 1, 2) FROM t"


def test_if_becomes_case(t):
    out = t.transpile("SELECT IF(a > 1, 'big', 'small') FROM t", "mysql", "postgres").sql
    assert out == "SELECT CASE WHEN a > 1 THEN 'big' ELSE 'small' END FROM t"


def test_now_and_ifnull_canonicalized(t):
    assert t.transpile("SELECT NOW() FROM t", "mysql", "mssql").sql == \
        "SELECT CURRENT_TIMESTAMP FROM t"
    assert t.transpile("SELECT IFNULL(a, 0) FROM t", "mysql", "postgres").sql == \
        "SELECT COALESCE(a, 0) FROM t"
    assert t.transpile("SELECT ISNULL(a, 0) FROM t", "mssql", "mysql").sql == \
        "SELECT COALESCE(a, 0) FROM t"


def test_group_concat_to_string_agg(t):
    assert t.transpile("SELECT GROUP_CONCAT(name) FROM t", "mysql", "postgres").sql == \
        "SELECT STRING_AGG(name) FROM t"


def test_string_escaping(t):
    out = t.transpile("SELECT 'it''s' FROM t", "mysql", "postgres").sql
    assert out == "SELECT 'it''s' FROM t"
