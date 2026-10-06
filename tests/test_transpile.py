"""多方言转译：标识符引用、大小写折叠、占位符、布尔字面量、分页、日期、拼接。"""


def test_identifier_quoting_and_placeholders(tp):
    out = tp.transpile("SELECT a, b FROM t WHERE c = ?", "sqlite", "postgres").sql
    assert out == 'SELECT "a", "b" FROM "t" WHERE "c" = $1'


def test_mysql_backticks_and_format_placeholder(tp):
    out = tp.transpile("SELECT a FROM t WHERE x = $1 AND y = $2",
                       "postgres", "mysql").sql
    assert out == "SELECT `a` FROM `t` WHERE `x` = %s AND `y` = %s"


def test_sqlserver_brackets_and_named_params(tp):
    out = tp.transpile("SELECT a FROM t WHERE x = ? AND y = ?",
                       "sqlite", "sqlserver").sql
    assert out == "SELECT [a] FROM [t] WHERE [x] = @p1 AND [y] = @p2"


def test_case_folding_postgres_lowercases_unquoted(tp):
    out = tp.transpile("SELECT UserName FROM Accounts", "postgres", "mysql").sql
    assert out == "SELECT `username` FROM `accounts`"


def test_quoted_identifiers_preserve_case(tp):
    out = tp.transpile('SELECT "UserName" FROM t', "postgres", "mysql").sql
    assert out == "SELECT `UserName` FROM `t`"


def test_input_style_does_not_change_output(tp):
    a = tp.transpile("select  A  from   T where X=?", "sqlite", "mysql").sql
    b = tp.transpile("SELECT A FROM T WHERE X = ?", "sqlite", "mysql").sql
    assert a == b


def test_boolean_literals(tp):
    assert "= 1" in tp.transpile("SELECT a FROM t WHERE f = TRUE",
                                 "postgres", "sqlite").sql
    assert "= TRUE" in tp.transpile("SELECT a FROM t WHERE f = TRUE",
                                    "sqlite", "postgres").sql


def test_concat_rewrite(tp):
    assert "CONCAT(`a`, `b`)" in tp.transpile(
        "SELECT a || b FROM t", "sqlite", "mysql").sql
    assert '"a" || "b"' in tp.transpile(
        "SELECT CONCAT(a, b) FROM t", "mysql", "postgres").sql


def test_pagination_limit_offset(tp):
    out = tp.transpile("SELECT a FROM t LIMIT 10 OFFSET 5",
                       "mysql", "postgres").sql
    assert out.endswith("LIMIT 10 OFFSET 5")


def test_pagination_offset_zero_omitted(tp):
    out = tp.transpile("SELECT a FROM t LIMIT 10 OFFSET 0",
                       "postgres", "mysql").sql
    assert out.endswith("LIMIT 10")
    assert "OFFSET" not in out


def test_pagination_offset_fetch_sqlserver(tp):
    out = tp.transpile("SELECT a FROM t LIMIT 10 OFFSET 5",
                       "mysql", "sqlserver").sql
    assert out.endswith("OFFSET 5 ROWS FETCH NEXT 10 ROWS ONLY")


def test_pagination_limit_only_sqlserver(tp):
    out = tp.transpile("SELECT a FROM t LIMIT 10", "mysql", "sqlserver").sql
    assert out.endswith("OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY")


def test_pagination_offset_without_limit_uses_sentinel(tp):
    out = tp.transpile("SELECT a FROM t OFFSET 5", "postgres", "mysql").sql
    assert out.endswith("LIMIT 18446744073709551615 OFFSET 5")


def test_pagination_huge_limit(tp):
    big = "SELECT a FROM t LIMIT 18446744073709551615 OFFSET 3"
    out = tp.transpile(big, "mysql", "postgres").sql
    assert "LIMIT 18446744073709551615 OFFSET 3" in out


def test_date_add_rewrite(tp):
    sql = "SELECT DATE_ADD(d, INTERVAL 2 DAY) FROM t"
    assert "+ INTERVAL '2 day'" in tp.transpile(sql, "mysql", "postgres").sql
    assert "DATEADD(day, 2, [d])" in tp.transpile(sql, "mysql", "sqlserver").sql
    assert "datetime(\"d\", '+2 day')" in tp.transpile(sql, "mysql", "sqlite").sql


def test_date_sub_sign_folded(tp):
    out = tp.transpile("SELECT DATE_SUB(d, INTERVAL 2 DAY) FROM t",
                       "mysql", "postgres").sql
    assert "- INTERVAL '2 day'" in out


def test_function_mapping(tp):
    out = tp.transpile("SELECT GROUP_CONCAT(a), LENGTH(b) FROM t",
                       "mysql", "sqlserver").sql
    assert "STRING_AGG([a])" in out and "LEN([b])" in out
