"""IR pydantic models + parse/serialize (F1).

Stub — implemented after the M0 test contract is committed red.
"""

from __future__ import annotations

from typing import Any


class IRObject:  # replaced by a pydantic model in the implementation
    pass


class AutomationConfig(IRObject):
    pass


class ScriptConfig(IRObject):
    pass


class HelperConfig(IRObject):
    pass


def parse(config: dict[str, Any], *, kind: str, key_hint: str | None = None) -> IRObject:
    raise NotImplementedError


def serialize(obj: IRObject) -> dict[str, Any]:
    raise NotImplementedError
