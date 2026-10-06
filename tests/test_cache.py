"""缓存：键覆盖方言组合与规则版本，规则更新后旧结果失效。"""
from transpiler.dialects import DialectRules, get_dialect, register_dialect


def test_cache_hit(tp):
    sql = "SELECT a FROM t WHERE x = ?"
    r1 = tp.transpile(sql, "sqlite", "mysql")
    r2 = tp.transpile(sql, "sqlite", "mysql")
    assert not r1.cached and r2.cached
    assert r1.sql == r2.sql


def test_cache_key_covers_dialect_pair(tp):
    sql = "SELECT a FROM t"
    tp.transpile(sql, "mysql", "postgres")
    r = tp.transpile(sql, "mysql", "sqlite")
    assert not r.cached  # 不同目标方言不共享缓存


def test_cache_invalidated_on_rule_update(tp):
    sql = "SELECT a FROM t"
    r1 = tp.transpile(sql, "mysql", "postgres")
    assert not r1.cached
    assert tp.transpile(sql, "mysql", "postgres").cached
    # 升级 postgres 规则版本：布尔字面量写法变化
    old = get_dialect("postgres")
    register_dialect(DialectRules(
        name="postgres", version="2.0.0",
        ident_quote_open=old.ident_quote_open,
        ident_quote_close=old.ident_quote_close,
        fold_unquoted=old.fold_unquoted,
        placeholder_style=old.placeholder_style,
        bool_literals=("True", "False"),
        pagination_style=old.pagination_style,
        limit_all_token=old.limit_all_token,
        concat_style=old.concat_style,
        date_arith_style=old.date_arith_style,
        function_map=dict(old.function_map)))
    r2 = tp.transpile(sql, "mysql", "postgres")
    assert not r2.cached  # 旧缓存失效
    out = tp.transpile("SELECT a FROM t WHERE f = TRUE", "mysql", "postgres").sql
    assert "True" in out  # 新规则生效


def test_lower_version_registration_ignored(tp):
    register_dialect(DialectRules(name="mysql", version="0.1.0"))
    assert get_dialect("mysql").version == "1.0.0"


def test_registration_order_independent(tp):
    """同一输入在任意注册顺序下结果一致。"""
    from transpiler.dialects import _reset_registry
    from transpiler.builtins import _BUILTINS
    sql = "SELECT a || 'x' FROM t WHERE b = ? LIMIT 1"
    expected = tp.transpile(sql, "sqlite", "postgres").sql
    _reset_registry()
    for rules in reversed(_BUILTINS):  # 反序注册
        register_dialect(rules)
    tp.clear_cache()
    assert tp.transpile(sql, "sqlite", "postgres").sql == expected


def test_clear_cache(tp):
    tp.transpile("SELECT a FROM t", "mysql", "postgres")
    assert tp.cache_size > 0
    tp.clear_cache()
    assert tp.cache_size == 0
