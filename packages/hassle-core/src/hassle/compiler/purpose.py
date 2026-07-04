"""Purpose-specific trigger/condition builder (DESIGN §5.4, §4 quirks; M1 test 10).

HA 2026.7 made a new namespaced trigger/condition vocabulary
(``trigger: <domain>.<event>``, e.g. ``motion.detected``) the UI default: one
*generic* typed builder rather than 200+ hand-written ones, since the
vocabulary is instance data validated in M3, not code (docs/m1-internal-api.md
§1). ``on(type_string, target=..., behavior=..., for_=..., **options)`` builds a
trigger; ``met(type_string, target=...)`` builds a condition. Both compile to
the exact stored shape pinned by ``fixtures/configs/automation_purpose_*.json``:
``{"trigger"|"condition": <type>, "target": {...}, "behavior": ..., "options": {...}}``.

Target forms (DESIGN §5.4): a plain entity_id string (the ``e.<domain>.<id>``
stub sugar is a later-milestone convenience over the same primitive),
``area("...")``, ``floor("...")``, ``label("...")``, ``device_id("...")``.
Type strings pass through unvalidated here — vocabulary validation is M3.
"""

from __future__ import annotations

from typing import Any

from hassle.compiler.durations import normalize_duration
from hassle.compiler.errors import CompileTimeBranchError
from hassle.compiler.spans import capture_span

Target = "str | AreaTarget | FloorTarget | LabelTarget | DeviceIdTarget"


class AreaTarget:
    def __init__(self, area_id: str) -> None:
        self.area_id = area_id

    def to_target_dict(self) -> dict[str, Any]:
        return {"area_id": self.area_id}


class FloorTarget:
    def __init__(self, floor_id: str) -> None:
        self.floor_id = floor_id

    def to_target_dict(self) -> dict[str, Any]:
        return {"floor_id": self.floor_id}


class LabelTarget:
    def __init__(self, label_id: str) -> None:
        self.label_id = label_id

    def to_target_dict(self) -> dict[str, Any]:
        return {"label_id": self.label_id}


class DeviceIdTarget:
    def __init__(self, device_id: str) -> None:
        self.device_id = device_id

    def to_target_dict(self) -> dict[str, Any]:
        return {"device_id": self.device_id}


def area(area_id: str) -> AreaTarget:
    """``area("office")`` — a purpose-trigger/condition target (DESIGN §5.4)."""
    return AreaTarget(area_id)


def floor(floor_id: str) -> FloorTarget:
    """``floor("upstairs")`` — a purpose-trigger/condition target (DESIGN §5.4)."""
    return FloorTarget(floor_id)


def label(label_id: str) -> LabelTarget:
    """``label("security")`` — a purpose-trigger/condition target (DESIGN §5.4)."""
    return LabelTarget(label_id)


def device_id(device_id: str) -> DeviceIdTarget:
    """``device_id("...")`` — a purpose-trigger/condition target (DESIGN §5.4)."""
    return DeviceIdTarget(device_id)


def _target_dict(target: Any) -> dict[str, Any]:
    if isinstance(target, str):
        # Bare entity ref: "domain.object_id" -> {"entity_id": "domain.object_id"}.
        return {"entity_id": target}
    return target.to_target_dict()  # type: ignore[no-any-return]


class PurposeTrigger:
    """``on(type_string, target=..., behavior=..., for_=..., **options)`` (DESIGN §5.4)."""

    def __init__(
        self,
        type_string: str,
        *,
        target: Any = None,
        behavior: str | None = None,
        for_: Any = None,
        **options: Any,
    ) -> None:
        self._type_string = type_string
        self._target = target
        self._behavior = behavior
        self._options: dict[str, Any] = dict(options)
        if for_ is not None:
            self._options["for"] = normalize_duration(for_)

    def to_trigger(self) -> dict[str, Any]:
        body: dict[str, Any] = {"trigger": self._type_string}
        if self._target is not None:
            body["target"] = _target_dict(self._target)
        if self._behavior is not None:
            body["behavior"] = self._behavior
        if self._options:
            body["options"] = dict(self._options)
        return body

    def _branch_repr(self) -> str:
        return f"on({self._type_string!r})"

    def __bool__(self) -> bool:
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


class PurposeCondition:
    """``met(type_string, target=...)`` (DESIGN §5.4)."""

    def __init__(self, type_string: str, *, target: Any = None) -> None:
        self._type_string = type_string
        self._target = target

    def to_condition(self) -> dict[str, Any]:
        body: dict[str, Any] = {"condition": self._type_string}
        if self._target is not None:
            body["target"] = _target_dict(self._target)
        return body

    def _branch_repr(self) -> str:
        return f"met({self._type_string!r})"

    def __bool__(self) -> bool:
        raise CompileTimeBranchError(self._branch_repr(), capture_span(depth=0))


def on(
    type_string: str,
    *,
    target: Any = None,
    behavior: str | None = None,
    for_: Any = None,
    **options: Any,
) -> PurposeTrigger:
    """Build a purpose-specific trigger (DESIGN §5.4, HA 2026.7+ vocabulary)."""
    return PurposeTrigger(type_string, target=target, behavior=behavior, for_=for_, **options)


def met(type_string: str, *, target: Any = None) -> PurposeCondition:
    """Build a purpose-specific condition (DESIGN §5.4, HA 2026.7+ vocabulary)."""
    return PurposeCondition(type_string, target=target)
