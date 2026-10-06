"""方言规则定义与可扩展注册表。每条规则带版本号。

注册顺序无关性：同名方言保留版本号最高者；版本相同保留先注册者。
转译结果只取决于 (方言名, 生效规则)，与 register 调用顺序无关。
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field

from .errors import UnknownDialectError


@dataclass(frozen=True)
class DialectRules:
    """一种方言的转译规则。version 变化会使相关缓存失效。"""
    name: str
    version: str = "1.0.0"
    # 标识符
    ident_quote_open: str = '"'
    ident_quote_close: str = '"'
    fold_unquoted: str = "lower"   # lower | upper | preserve
    # 参数占位符样式: qmark(?) / format(%s) / numeric_dollar($1) / named_at(@p1)
    placeholder_style: str = "qmark"
    # 布尔字面量 (true, false)
    bool_literals: tuple[str, str] = ("TRUE", "FALSE")
    # 分页样式: limit_offset / offset_fetch
    pagination_style: str = "limit_offset"
    # 只有 OFFSET 没有 LIMIT 时使用的极限行数哨兵（limit_offset 样式下）
    limit_all_token: str = "ALL"
    # 字符串拼接: operator(||) / function(CONCAT)
    concat_style: str = "operator"
    # 日期加减样式:
    #   interval_op  -> x + INTERVAL 'n unit'      (postgres)
    #   interval_kw  -> DATE_ADD(x, INTERVAL n u)  (mysql)
    #   dateadd      -> DATEADD(unit, n, x)        (sqlserver)
    #   datetime_mod -> datetime(x, '+n unit')     (sqlite)
    date_arith_style: str = "interval_op"
    # 规范函数名 -> 目标方言函数名；不在表中的规范函数视为不支持
    function_map: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("方言名不能为空")
        _version_key(self.version)  # 校验版本号格式


_lock = threading.RLock()
_REGISTRY: dict[str, DialectRules] = {}
# 注册代际：每次注册/覆盖都递增，用于缓存失效
_generation: int = 0


def _version_key(v: str) -> tuple:
    try:
        return tuple(int(p) for p in str(v).split("."))
    except ValueError:
        raise ValueError(f"非法版本号 {v!r}，应为形如 '1.2.3' 的数字串") from None


def register_dialect(rules: DialectRules) -> None:
    """注册方言规则；同名时高版本覆盖低版本，与注册顺序无关。"""
    global _generation
    key = rules.name.lower()
    with _lock:
        existing = _REGISTRY.get(key)
        if existing is not None and _version_key(existing.version) > _version_key(rules.version):
            return  # 已有更高版本，忽略
        if existing == rules:
            return  # 完全相同的规则，幂等
        _REGISTRY[key] = rules
        _generation += 1


def get_dialect(name: str) -> DialectRules:
    with _lock:
        rules = _REGISTRY.get(name.lower())
    if rules is None:
        known = ", ".join(sorted(_REGISTRY)) or "(空)"
        raise UnknownDialectError(
            f"未知方言 {name!r}，已注册方言: {known}")
    return rules


def list_dialects() -> list[DialectRules]:
    with _lock:
        return [_REGISTRY[k] for k in sorted(_REGISTRY)]


def registry_generation() -> int:
    """当前注册表代际，随规则变更递增。"""
    with _lock:
        return _generation


def _reset_registry() -> None:
    """仅供测试：清空注册表。"""
    global _generation
    with _lock:
        _REGISTRY.clear()
        _generation += 1
