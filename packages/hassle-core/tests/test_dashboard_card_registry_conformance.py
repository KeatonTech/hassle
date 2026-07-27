"""Table-driven CARD_REGISTRY conformance (review-round item 9).

Replaces per-family spot coverage of the same three questions with ONE test
that walks `CARD_REGISTRY` itself and drives every registered builder
generically:

- `visibility=` round-trips to the stored `visibility` list;
- `extra={...}` round-trips a genuinely unmodelled key into the card body;
- `extra={"type": ...}` (a key every row's `declared` set is guaranteed to
  contain, per `test_dashboard_card_registry.py`) raises
  `ExtraShadowsKwargError`.

Future-proofs new families: a family that registers a `CardSpec` row but
never wires `visibility=`/`extra=` correctly fails THIS test without any
family-specific code being written for it, as long as its builder's required
parameters follow the vocabulary's existing naming convention (`entity`,
`entities`, `area`, `url`, `image`, `content`, or a `*varargs` rows/conditions
parameter) -- the same convention every one of the 47 registered builders
already follows (pinned by `_minimal_call`'s exhaustiveness check below).
"""

from __future__ import annotations

import inspect
from typing import Any

import pytest

import hassle.cards as c
from hassle.cards import cond
from hassle.compiler.dashboards.card_registry import CARD_REGISTRY, CardSpec
from hassle.compiler.dashboards.errors import ExtraShadowsKwargError
from hassle.compiler.dashboards.recorder import dashboard_recording
from hassle.compiler.dashboards.structure import raw_card, section, view

_ENTITY = "sensor.conformance_probe"

#: Placeholder values for every required-parameter NAME this vocabulary uses.
#: Exhaustive on purpose: `_minimal_call` raises loudly for any name not
#: listed here, so a future builder with an unanticipated required-parameter
#: name fails with a clear message instead of a confusing downstream error.
_PLACEHOLDERS: dict[str, Any] = {
    "entity": _ENTITY,
    "entities": [_ENTITY],
    "area": "living_room",
    "url": "http://example.invalid",
    "image": "http://example.invalid/image.png",
    "content": "conformance probe",
}


def _minimal_call(fn: Any) -> tuple[list[Any], dict[str, Any]]:
    """The smallest `(args, kwargs)` that satisfies `fn`'s REQUIRED parameters."""
    args: list[Any] = []
    kwargs: dict[str, Any] = {}
    for p in inspect.signature(fn).parameters.values():
        if p.default is not inspect.Parameter.empty:
            continue
        if p.kind is inspect.Parameter.VAR_POSITIONAL:
            value = cond.state(_ENTITY, "on") if p.name == "conditions" else _ENTITY
            args.append(value)
            continue
        if p.name not in _PLACEHOLDERS:
            raise AssertionError(
                f"conformance test has no placeholder for required parameter {p.name!r} "
                f"of {fn!r} -- add one to _PLACEHOLDERS."
            )
        value = _PLACEHOLDERS[p.name]
        if p.kind is inspect.Parameter.KEYWORD_ONLY:
            kwargs[p.name] = value
        else:
            args.append(value)
    return args, kwargs


def _find_card(config: dict[str, Any], card_type: str) -> dict[str, Any]:
    """The first card of `card_type`, found by walking `views` -> `cards`/
    (`sections` -> `cards`) -> `cards`/`card`.

    Never matches a SECTION node itself, even though a `section()` also
    stores `{"type": "grid", ...}` (§6.1.1's grid-vs-section
    disambiguation) -- a stored card is only ever reached through a
    `cards`/`card` key, never `sections`, which is exactly the position
    CARD_REGISTRY (vs. STRUCTURE_REGISTRY) governs. Matching indiscriminately
    would find the wrong node for `card_type="grid"`.
    """
    for v in config.get("views", []):
        # a view's OWN flat `cards` list (masonry/panel/…) -- items here ARE
        # real cards, eligible to match directly.
        for item in v.get("cards") or []:
            found = _walk(item, card_type)
            if found is not None:
                return found
        # a `sections` view's sections are NOT cards themselves -- only THEIR
        # `cards` list holds real cards.
        for sect in v.get("sections") or []:
            for item in sect.get("cards") or []:
                found = _walk(item, card_type)
                if found is not None:
                    return found
    raise AssertionError(f"{card_type!r} not found in compiled config: {config!r}")


def _walk(node: Any, card_type: str) -> dict[str, Any] | None:
    if not isinstance(node, dict):
        return None
    if node.get("type") == card_type:
        return node
    for key in ("cards", "card"):
        child = node.get(key)
        if isinstance(child, list):
            for item in child:
                found = _walk(item, card_type)
                if found is not None:
                    return found
        elif isinstance(child, dict):
            found = _walk(child, card_type)
            if found is not None:
                return found
    return None


def _open(spec: CardSpec, fn: Any, args: list[Any], kwargs: dict[str, Any]) -> None:
    """Call `fn`, opening its `with` block (and one child card, if it takes
    one) when `spec` says it is a container."""
    if not spec.context_manager:
        fn(*args, **kwargs)
        return
    with fn(*args, **kwargs):
        if spec.container == "card":
            raw_card({"type": "markdown", "content": "conformance child"})


@pytest.mark.parametrize("card_type", sorted(CARD_REGISTRY), ids=sorted(CARD_REGISTRY))
def test_visibility_and_extra_round_trip(card_type: str) -> None:
    spec = CARD_REGISTRY[card_type]
    fn = getattr(c, spec.builder.removeprefix("c."))
    args, kwargs = _minimal_call(fn)
    kwargs = {
        **kwargs,
        "visibility": cond.state("light.conformance_probe", "on"),
        "extra": {"__conformance_extra__": True},
    }

    with dashboard_recording(url_path="conformance-a-b") as rec, view(title="V"), section():
        _open(spec, fn, args, kwargs)
    card = _find_card(rec.build_config(), card_type)

    assert card["visibility"] == [
        {"condition": "state", "entity": "light.conformance_probe", "state": "on"}
    ]
    assert card["__conformance_extra__"] is True


@pytest.mark.parametrize("card_type", sorted(CARD_REGISTRY), ids=sorted(CARD_REGISTRY))
def test_extra_shadowing_type_raises(card_type: str) -> None:
    # Every row's `declared` set is guaranteed to contain "type"
    # (test_dashboard_card_registry.py), so this is a universal shadow probe
    # that needs no per-builder knowledge of its OTHER declared keys.
    spec = CARD_REGISTRY[card_type]
    fn = getattr(c, spec.builder.removeprefix("c."))
    args, kwargs = _minimal_call(fn)
    kwargs = {**kwargs, "extra": {"type": "shadow-attempt"}}

    with dashboard_recording(url_path="conformance-shadow"):  # noqa: SIM117
        with pytest.raises(ExtraShadowsKwargError):
            with view(title="V"), section():
                _open(spec, fn, args, kwargs)
