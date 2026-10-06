"""方言注册表。

- 新增方言只需 register()，转译核心不感知具体方言。
- 每条规则带版本号；同名同版本重复注册且内容一致时为幂等，
  内容冲突则报错；同名新版本视为规则升级。
- 所有枚举操作按方言名排序，保证任意注册顺序下行为一致。
"""

from __future__ import annotations

import threading
from typing import Dict, List, Tuple

from .dialects import BUILTIN_DIALECTS, Dialect
from .errors import UnknownDialectError


class DialectRegistry:
    def __init__(self, dialects: Tuple[Dialect, ...] = ()):
        self._lock = threading.Lock()
        self._dialects: Dict[str, Dialect] = {}
        for d in dialects:
            self.register(d)

    def register(self, dialect: Dialect) -> None:
        with self._lock:
            existing = self._dialects.get(dialect.name)
            if existing is not None:
                if existing.version == dialect.version:
                    if existing != dialect:
                        raise ValueError(
                            f"dialect {dialect.name!r} version {dialect.version} "
                            "already registered with different rules")
                    return  # 幂等
                # 同名新版本：规则升级，旧缓存键因版本不同自然失效
            self._dialects[dialect.name] = dialect

    def get(self, name: str) -> Dialect:
        dialect = self._dialects.get(name)
        if dialect is None:
            raise UnknownDialectError(name, available=self.names())
        return dialect

    def names(self) -> List[str]:
        return sorted(self._dialects)

    def all(self) -> List[Dialect]:
        return [self._dialects[n] for n in self.names()]


def default_registry() -> DialectRegistry:
    """包含全部内置方言的注册表。"""
    return DialectRegistry(BUILTIN_DIALECTS)
