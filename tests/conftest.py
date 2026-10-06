import pytest

from transpiler.builtins import register_builtins
from transpiler.dialects import _reset_registry
from transpiler.engine import Transpiler


@pytest.fixture(autouse=True)
def fresh_registry():
    _reset_registry()
    register_builtins()
    yield


@pytest.fixture()
def tp():
    return Transpiler()
