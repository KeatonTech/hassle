"""Classic condition builders + combinators (DESIGN §5.4) — triggers/conditions workstream.

``trigger_condition`` is the ``condition: trigger`` block referencing a trigger's
``id=`` (fixture: ``automation_condition_trigger.json``). ``any_of``/``all_of``/
``not_`` compile to HA's ``or``/``and``/``not`` condition blocks
(``automation_condition_and_or_not.json``) and keep the ``__bool__`` trap
(DESIGN §5.5) so a native Python ``if``/``bool()`` on a combinator fails loudly,
same as any leaf condition expression.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from hassle_core.compiler.errors import CompileTimeBranchError
from hassle_core.compiler.spans import capture_span


@runtime_checkable
class _ConditionLike(Protocol):
    def to_condition(self) -> dict[str, Any]: ...


class TriggerConditionExpr:
    """``trigger_condition(trigger_id)`` -> ``{"condition": "trigger", "id": ...}``."""

    def __init__(self, trigger_id: str) -> None:
        self._trigger_id = trigger_id

    def to_condition(self) -> dict[str, Any]:
        return {"condition": "trigger", "id": self._trigger_id}

    def _branch_repr(self) -> str:
        return f"trigger_condition({self._trigger_id!r})"

    def __bool__(self) -> bool:
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


def trigger_condition(trigger_id: str) -> TriggerConditionExpr:
    """Build a ``condition: trigger`` block referencing a trigger ``id=`` (DESIGN §5.4)."""
    return TriggerConditionExpr(trigger_id)


class _CombinatorExpr:
    """Shared body for ``any_of``/``all_of``/``not_`` (DESIGN §5.4)."""

    def __init__(self, keyword: str, conditions: tuple[_ConditionLike, ...]) -> None:
        self._keyword = keyword
        self._conditions = conditions

    def to_condition(self) -> dict[str, Any]:
        return {
            "condition": self._keyword,
            "conditions": [c.to_condition() for c in self._conditions],
        }

    def _branch_repr(self) -> str:
        return f"{self._keyword}(...)"

    def __bool__(self) -> bool:
        # Extends the core __bool__ trap (DESIGN §5.5) to combinators: a native
        # Python `if`/`bool()` on `any_of(...)`/`all_of(...)`/`not_(...)` must
        # fail loudly, exactly like any leaf condition expression.
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


def any_of(*conditions: _ConditionLike) -> _CombinatorExpr:
    """``any_of(...)`` compiles to an ``or`` condition block (DESIGN §5.4)."""
    return _CombinatorExpr("or", conditions)


def all_of(*conditions: _ConditionLike) -> _CombinatorExpr:
    """``all_of(...)`` compiles to an ``and`` condition block (DESIGN §5.4)."""
    return _CombinatorExpr("and", conditions)


def not_(*conditions: _ConditionLike) -> _CombinatorExpr:
    """``not_(...)`` compiles to a ``not`` condition block (DESIGN §5.4)."""
    return _CombinatorExpr("not", conditions)
