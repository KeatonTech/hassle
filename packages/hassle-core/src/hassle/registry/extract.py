"""Reference extraction from compiled IR (DESIGN §9 tier 2).

Walks every trigger/condition/action dict in a `CompileResult` and yields a
`Reference` for each entity_id / area_id / floor_id / label_id / device_id /
purpose-vocabulary-type it finds — in classic block fields (`entity_id`,
bare or list), purpose-trigger/condition `target:` blocks (all five keys,
single value or list), Jinja template strings (AST-walked, with a regex
fallback), and `raw_*` blocks (which are just plain dicts by this point, no
different from any other trigger/condition/action body).

Each `Reference` carries the file:line span of the DSL call that produced the
block it came from (M1 spans, `CompileResult.spans_for`), so a Finding built
from it can always point at a source line (subject to the source having a
span at all — helper declarations and prebuilt objects may not).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, cast

import jinja2
from jinja2 import nodes as jinja_nodes

from hassle.compiler.bundle import CompileResult
from hassle.compiler.spans import SourceSpan
from hassle.ir.models import IRObject


def as_dict_list(value: Any) -> list[dict[str, Any]]:
    """Narrow an ``Any``-typed ``to_ha()``-shaped value to a typed list of
    dicts (dropping any non-dict items), isolating the one trust boundary
    where compiled IR's deliberately untyped ``to_ha()`` output enters this
    package's otherwise fully-typed code (pyright --strict, R7). Shared with
    :mod:`hassle.registry.validate`, which walks the same IR shape.
    """
    if not isinstance(value, list):
        return []
    items = cast("list[Any]", value)
    return [cast(dict[str, Any], item) for item in items if isinstance(item, dict)]


# HA domains the Jinja-string regex fallback restricts itself to, so we don't
# treat arbitrary "word.word" substrings (e.g. part of a sentence) as an
# entity reference. This list is deliberately generous (real domains from the
# fixture corpus plus HA's common built-ins) rather than exhaustive; it only
# gates the *regex fallback* used when the Jinja AST walk can't resolve a
# literal argument, so under-matching there only means a missed reference,
# never a false positive on a random word (the caller already knows this
# extraction is best-effort inside prose-shaped Jinja).
_KNOWN_ISH_DOMAINS = {
    "light",
    "switch",
    "binary_sensor",
    "sensor",
    "climate",
    "media_player",
    "person",
    "device_tracker",
    "cover",
    "lock",
    "fan",
    "camera",
    "input_boolean",
    "input_number",
    "input_select",
    "input_text",
    "input_datetime",
    "input_button",
    "counter",
    "timer",
    "schedule",
    "number",
    "select",
    "automation",
    "script",
    "notify",
    "zone",
    "geo_location",
    "calendar",
    "weather",
    "sun",
    "update",
    "siren",
    "image",
    "button",
    "humidifier",
    "vacuum",
    "water_heater",
    "alarm_control_panel",
    "event",
    "scene",
    "group",
}

_ENTITY_ID_RE = re.compile(r"\b([a-z_]+)\.([a-z0-9_]+)\b")

# Position kinds this module distinguishes (used only for readability at call
# sites / debugging; validation keys off the individual id fields).
_TARGET_KEYS = ("entity_id", "area_id", "floor_id", "label_id", "device_id")


@dataclass(frozen=True)
class Reference:
    """A single entity/area/floor/label/device reference found in the IR."""

    entity_id: str | None
    area_id: str | None
    floor_id: str | None
    label_id: str | None
    device_id: str | None
    object_key: str
    section: str  # "triggers" | "conditions" | "actions"
    span: SourceSpan | None
    source: str  # short human tag: "entity_id" | "target" | "template" | "raw" | ...


def _as_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return cast("list[Any]", value)
    return [value]


def _extract_entity_ids_from_jinja(text: str) -> set[str]:
    """Entity ids referenced inside a Jinja string's `states()`/`state_attr()`/
    `is_state()` calls — AST-first, regex fallback restricted to known domains.
    """
    found: set[str] = set()
    try:
        ast = jinja2.Environment().parse(text)
    except jinja2.TemplateSyntaxError:
        ast = None
    if ast is not None:
        for node in ast.find_all(jinja_nodes.Call):
            func = node.node
            func_name = getattr(func, "name", None)
            if func_name in ("states", "state_attr", "is_state") and node.args:
                first = node.args[0]
                if isinstance(first, jinja_nodes.Const) and isinstance(first.value, str):
                    found.add(first.value)
    # Regex fallback: catches anything the AST walk didn't resolve (e.g. a
    # dynamic/non-literal first arg elsewhere in the string, or a syntax the
    # parser choked on) — restricted to known-ish domains to avoid noise.
    for m in _ENTITY_ID_RE.finditer(text):
        candidate = f"{m.group(1)}.{m.group(2)}"
        if m.group(1) in _KNOWN_ISH_DOMAINS:
            found.add(candidate)
    return found


def _target_refs(target: dict[str, Any]) -> list[tuple[str, str]]:
    """``target: {...}`` -> list of (key, value) pairs, list-values expanded."""
    out: list[tuple[str, str]] = []
    for key in _TARGET_KEYS:
        if key not in target:
            continue
        for value in _as_list(target[key]):
            if isinstance(value, str):
                out.append((key, value))
    return out


def _make_ref(
    *,
    key: str,
    value: str,
    object_key: str,
    section: str,
    span: SourceSpan | None,
    source: str,
) -> Reference:
    return Reference(
        entity_id=value if key == "entity_id" else None,
        area_id=value if key == "area_id" else None,
        floor_id=value if key == "floor_id" else None,
        label_id=value if key == "label_id" else None,
        device_id=value if key == "device_id" else None,
        object_key=object_key,
        section=section,
        span=span,
        source=source,
    )


def _walk_block(
    block: dict[str, Any],
    *,
    object_key: str,
    section: str,
    span: SourceSpan | None,
) -> list[Reference]:
    refs: list[Reference] = []

    # Top-level entity_id (classic trigger/condition/action shape, bare or list),
    # e.g. {"trigger": "state", "entity_id": "binary_sensor.x"} or a raw block's
    # {"service": "...", "entity_id": "..."} legacy longhand.
    if "entity_id" in block:
        for value in _as_list(block["entity_id"]):
            if isinstance(value, str):
                refs.append(
                    _make_ref(
                        key="entity_id",
                        value=value,
                        object_key=object_key,
                        section=section,
                        span=span,
                        source="entity_id",
                    )
                )

    # Top-level device_id (classic `device` trigger/condition raw shape),
    # e.g. {"platform": "device", "device_id": "abc123", ...}.
    if isinstance(block.get("device_id"), str):
        refs.append(
            _make_ref(
                key="device_id",
                value=block["device_id"],
                object_key=object_key,
                section=section,
                span=span,
                source="device_id",
            )
        )

    # A bare `zone` field referencing a zone entity (zone/geo_location triggers).
    if isinstance(block.get("zone"), str) and "." in block["zone"]:
        refs.append(
            _make_ref(
                key="entity_id",
                value=block["zone"],
                object_key=object_key,
                section=section,
                span=span,
                source="zone",
            )
        )

    # `target: {...}` block (purpose triggers/conditions AND service-call actions).
    target = block.get("target")
    if isinstance(target, dict):
        for key, value in _target_refs(cast(dict[str, Any], target)):
            refs.append(
                _make_ref(
                    key=key,
                    value=value,
                    object_key=object_key,
                    section=section,
                    span=span,
                    source="target",
                )
            )

    # `data`/`service_data` dicts: look for plausibly entity-id-shaped values
    # under an `entity_id` key (some raw/legacy bodies nest it there) and scan
    # string values for Jinja for template-embedded refs.
    for data_key in ("data", "service_data"):
        data_raw = block.get(data_key)
        if isinstance(data_raw, dict):
            data = cast(dict[str, Any], data_raw)
            if "entity_id" in data:
                for value in _as_list(data["entity_id"]):
                    if isinstance(value, str):
                        refs.append(
                            _make_ref(
                                key="entity_id",
                                value=value,
                                object_key=object_key,
                                section=section,
                                span=span,
                                source=data_key,
                            )
                        )
            for value in data.values():
                if isinstance(value, str) and "{{" in value:
                    for eid in _extract_entity_ids_from_jinja(value):
                        refs.append(
                            _make_ref(
                                key="entity_id",
                                value=eid,
                                object_key=object_key,
                                section=section,
                                span=span,
                                source="template",
                            )
                        )

    # Any other top-level string field that looks like a Jinja template
    # (value_template, condition template, wait_template, etc.) or itself
    # contains "{{" — covers `template` trigger/condition value_template and
    # arbitrary raw-block template strings.
    for key, value in block.items():
        if key in ("data", "service_data", "target"):
            continue  # handled above
        if isinstance(value, str) and "{{" in value:
            for eid in _extract_entity_ids_from_jinja(value):
                refs.append(
                    _make_ref(
                        key="entity_id",
                        value=eid,
                        object_key=object_key,
                        section=section,
                        span=span,
                        source="template",
                    )
                )

    return refs


def extract_references(result: CompileResult) -> list[Reference]:
    """Extract every entity/area/floor/label/device reference from compiled IR."""
    refs: list[Reference] = []
    for object_key, obj in result.objects.items():
        body = obj.to_ha()
        for section in ("triggers", "conditions", "actions"):
            blocks = as_dict_list(body.get(section))
            spans = _spans_for_object(result, obj, section, block_count=len(blocks))
            for i, block in enumerate(blocks):
                span = spans[i] if i < len(spans) else None
                refs.extend(_walk_block(block, object_key=object_key, section=section, span=span))
    return refs


def _spans_for_object(
    result: CompileResult, obj: IRObject, section: str, *, block_count: int
) -> list[SourceSpan | None]:
    """Per-index span lookup (parallel to the block list) via the public
    per-item accessor (``CompileResult.span_at``, M3 addition to bundle.py).
    """
    return [result.span_at(obj, section, i) for i in range(block_count)]
