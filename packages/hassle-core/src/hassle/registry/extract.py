"""Reference extraction from compiled IR (DESIGN §9 tier 2).

Walks every trigger/condition/action dict in a `CompileResult` and yields a
`Reference` for each entity_id / area_id / floor_id / label_id / device_id /
purpose-vocabulary-type it finds — in classic block fields (`entity_id`,
bare or list), purpose-trigger/condition `target:` blocks (all five keys,
single value or list), Jinja template strings (AST-walked, with a regex
fallback), and `raw_*` blocks (which are just plain dicts by this point, no
different from any other trigger/condition/action body).

**Recursive descent into nested action containers (reviewer B1 fix).** An
action list is not flat: `if`/`choose`/`repeat`/`parallel` are themselves
action-shaped dicts whose *own* fields hold further trigger/condition/action
lists (`then`/`else`, `conditions`+`sequence`, `sequence`, `default`,
`while`/`until`), and `wait_for_trigger` holds a nested trigger list. A block
found only at the top of `actions`/`triggers`/`conditions` would silently miss
every entity reference buried inside one of these containers -- exactly the
gap the reviewer's three-position probe (if_then body, repeat_count body,
parallel body) caught. `_walk_block` therefore recurses into every nested
container key after processing the container's own fields, dispatching each
nested list to the right *position* (condition-shaped lists validate their
`condition`/`type` field against the condition vocabulary; action-shaped lists
against nothing extra; `wait_for_trigger`'s list is trigger-shaped) so a
purpose type nested inside, say, a `repeat.while` list is still checked
against the right (`conditions`) vocabulary half.

Nested blocks do not carry their own per-item span in `CompileResult` (the
recording machinery gives the *container* action one span at its own
`with if_then(...):`-style call site; the bodies nested inside it are folded
into that single recorded node with no separate span retained per inner
item, docs/m1-internal-api.md §2) -- so every reference found while recursing
inherits the *container's* span. This is coarser than a top-level reference's
span (it points at the `with if_then(...):` line, not the exact nested
`service(...)` call), but it is still a real, correct file:line rather than
none at all, and is the most precise span the current span-tracking
architecture can give without changing the M1-frozen recording internals.

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

# §36.1 fix (docs/ha-api-notes.md): matches the WHOLE dotted identifier chain
# a candidate `domain.object_id` pair sits in (`[ident.]*domain.object_id`,
# greedy on the leading part), so the code can reject a candidate that is
# merely the last two segments of a LONGER chain -- a Jinja *variable path*
# like `wait.trigger.event.data.action` or `trigger.event.data.action`, never
# a literal entity id -- rather than a standalone `domain.object_id` token
# with nothing dotted in front of it. Matching greedily (not just one
# preceding hop) matters: non-overlapping regex scanning would otherwise
# consume `wait.trigger.event` as one match and restart from `data.action`,
# which -- with only a single-hop lookback -- would slip through unflagged
# as if it had no preceding identifier at all. A genuine entity id is never
# itself an attribute of some other name in these templates (it appears bare,
# as a string literal argument or a whole identifier), so this exclusion only
# ever screens out the false-positive shape: `event.data` inside
# `wait.trigger.event.data.action` is excluded (a longer chain), but a real
# domain reference like `event.doorbell` in
# `is_state('event.doorbell', 'pressed')` (no dotted identifier before it)
# still matches.
_ENTITY_ID_RE = re.compile(
    r"\b(?:(?P<prefix>[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)*)\.)?"
    r"(?P<domain>[a-z_]+)\.(?P<object_id>[a-z0-9_]+)\b"
)

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


def _is_template_string(value: Any) -> bool:
    """A Jinja placeholder (e.g. ``"{{ repeat.item }}"``) is a *runtime*
    reference, never a literal entity/area/floor/label/device id -- treating
    one as a literal id is a false positive (seen in `repeat_for_each`'s
    `target: {"entity_id": "{{ repeat.item }}"}`). Such strings are only ever
    scanned for embedded `states()`/`state_attr()`/`is_state()` calls
    (`_extract_entity_ids_from_jinja`), never taken at face value elsewhere.
    """
    return isinstance(value, str) and "{{" in value


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
    # parser choked on) — restricted to known-ish domains to avoid noise, and
    # (§36.1) skipped when the candidate is itself preceded by another dotted
    # identifier (a `wait.`/`trigger.`-rooted variable path, not a literal
    # entity id — see `_ENTITY_ID_RE`'s docstring comment above).
    for m in _ENTITY_ID_RE.finditer(text):
        if m.group("prefix") is not None:
            continue
        domain, object_id = m.group("domain"), m.group("object_id")
        candidate = f"{domain}.{object_id}"
        if domain in _KNOWN_ISH_DOMAINS:
            found.add(candidate)
    return found


def _target_refs(target: dict[str, Any]) -> list[tuple[str, str]]:
    """``target: {...}`` -> list of (key, value) pairs, list-values expanded.

    A template-valued entry (e.g. ``target={"entity_id": "{{ repeat.item }}"}``)
    is never a literal id, so it is excluded here -- but (coordinator
    fix-forward) it is not simply dropped: the caller still scans it for
    embedded ``states(...)``-style calls via ``_literal_or_scanned_ids``.
    """
    out: list[tuple[str, str]] = []
    for key in _TARGET_KEYS:
        if key not in target:
            continue
        for value in _as_list(target[key]):
            if isinstance(value, str) and not _is_template_string(value):
                out.append((key, value))
    return out


def _target_template_strings(target: dict[str, Any]) -> list[str]:
    """The template-valued strings `_target_refs` excluded, for embedded-Jinja
    scanning (coordinator fix-forward: uniform scan coverage across positions).
    """
    out: list[str] = []
    for key in _TARGET_KEYS:
        if key not in target:
            continue
        for value in _as_list(target[key]):
            if isinstance(value, str) and _is_template_string(value):
                out.append(value)
    return out


_REGISTRY_UUID_RE = re.compile(r"[0-9a-f]{32}\Z")


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


def _scanned_template_refs(
    text: str, *, object_key: str, section: str, span: SourceSpan | None, source: str
) -> list[Reference]:
    """Scan a template-valued string (one `_is_template_string` excluded from
    literal-id treatment) for embedded `states(...)`/`state_attr(...)`/
    `is_state(...)` entity references (coordinator fix-forward: every
    guard-skipped template string -- target values, top-level entity_id/
    device_id/zone, repeat.for_each items -- gets the same scan coverage
    `data`/`service_data` values and the generic any-other-field pass already
    had; a placeholder with no embedded call, e.g. `{{ repeat.item }}`,
    legitimately yields nothing here).
    """
    return [
        _make_ref(
            key="entity_id",
            value=eid,
            object_key=object_key,
            section=section,
            span=span,
            source=source,
        )
        for eid in _extract_entity_ids_from_jinja(text)
    ]


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
            if not isinstance(value, str):
                continue
            if _is_template_string(value):
                refs.extend(
                    _scanned_template_refs(
                        value,
                        object_key=object_key,
                        section=section,
                        span=span,
                        source="entity_id",
                    )
                )
            else:
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
    device_id_value = block.get("device_id")
    if isinstance(device_id_value, str):
        if _is_template_string(device_id_value):
            refs.extend(
                _scanned_template_refs(
                    device_id_value,
                    object_key=object_key,
                    section=section,
                    span=span,
                    source="device_id",
                )
            )
        else:
            refs.append(
                _make_ref(
                    key="device_id",
                    value=device_id_value,
                    object_key=object_key,
                    section=section,
                    span=span,
                    source="device_id",
                )
            )

    # A bare `zone` field referencing a zone entity (zone/geo_location triggers).
    zone_value = block.get("zone")
    if isinstance(zone_value, str):
        if _is_template_string(zone_value):
            refs.extend(
                _scanned_template_refs(
                    zone_value, object_key=object_key, section=section, span=span, source="zone"
                )
            )
        elif "." in zone_value:
            refs.append(
                _make_ref(
                    key="entity_id",
                    value=zone_value,
                    object_key=object_key,
                    section=section,
                    span=span,
                    source="zone",
                )
            )

    # `target: {...}` block (purpose triggers/conditions AND service-call actions).
    target = block.get("target")
    if isinstance(target, dict):
        target_dict = cast(dict[str, Any], target)
        for key, value in _target_refs(target_dict):
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
        # Template-valued target entries (e.g. `{"entity_id": "{{ states(...) }}"}`)
        # were excluded above as literal ids -- scan them for embedded refs too
        # (coordinator fix-forward), same as any other template-shaped string.
        for template_value in _target_template_strings(target_dict):
            refs.extend(
                _scanned_template_refs(
                    template_value,
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
                    if isinstance(value, str) and not _is_template_string(value):
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
                if isinstance(value, str) and _is_template_string(value):
                    refs.extend(
                        _scanned_template_refs(
                            value,
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
        if isinstance(value, str) and _is_template_string(value):
            refs.extend(
                _scanned_template_refs(
                    value, object_key=object_key, section=section, span=span, source="template"
                )
            )

    refs.extend(_walk_nested_containers(block, object_key=object_key, span=span))

    return refs


# Nested container keys that hold a *condition*-position list (validated the
# same way `conditions` is): `if`'s own condition list, a `choose` branch's
# `conditions`, and `repeat`'s `while`/`until` condition lists.
_NESTED_CONDITION_KEYS = ("if", "conditions", "while", "until")

# Nested container keys that hold an *action*-position list: `if`'s `then`/
# `else`, a `choose` branch's or `repeat`'s `sequence`, and `choose`'s
# `default`. Plain `sequence` (scripts, `repeat_for_each`) is included too.
_NESTED_ACTION_KEYS = ("then", "else", "sequence", "default")


def _walk_nested_containers(
    block: dict[str, Any], *, object_key: str, span: SourceSpan | None
) -> list[Reference]:
    """Recurse into `if`/`choose`/`repeat`/`parallel`/`wait_for_trigger`'s own
    nested trigger/condition/action lists (reviewer B1). Every reference found
    while recursing inherits the container's own span (see module docstring:
    nested bodies have no separate per-item span of their own).
    """
    refs: list[Reference] = []

    for key in _NESTED_CONDITION_KEYS:
        for nested in as_dict_list(block.get(key)):
            refs.extend(_walk_block(nested, object_key=object_key, section="conditions", span=span))

    for key in _NESTED_ACTION_KEYS:
        for nested in as_dict_list(block.get(key)):
            refs.extend(_walk_block(nested, object_key=object_key, section="actions", span=span))

    # `choose`: a top-level LIST of {"conditions": [...], "sequence": [...]}
    # branches (distinct from the `if`/`repeat`/`parallel` dict-shaped
    # containers above).
    for branch in as_dict_list(block.get("choose")):
        refs.extend(_walk_nested_containers(branch, object_key=object_key, span=span))

    # `parallel`: a top-level LIST of {"sequence": [...]} branches.
    for branch in as_dict_list(block.get("parallel")):
        refs.extend(_walk_nested_containers(branch, object_key=object_key, span=span))

    # `repeat`: a single dict (not a list) holding `count`/`while`/`until`/
    # `for_each` + `sequence` -- walk it as one more nested block.
    repeat_body_raw = block.get("repeat")
    if isinstance(repeat_body_raw, dict):
        repeat_body = cast(dict[str, Any], repeat_body_raw)
        refs.extend(_walk_nested_containers(repeat_body, object_key=object_key, span=span))
        # `for_each` items are themselves plain entity-id-shaped strings in the
        # DSL's own goldens (e.g. `repeat_for_each(["light.bedroom", ...])`),
        # not dicts -- catch them here since `as_dict_list` would drop them.
        for item in _as_list(repeat_body.get("for_each")):
            if not isinstance(item, str):
                continue
            if _is_template_string(item):
                refs.extend(
                    _scanned_template_refs(
                        item,
                        object_key=object_key,
                        section="actions",
                        span=span,
                        source="repeat_for_each",
                    )
                )
            elif "." in item:
                refs.append(
                    _make_ref(
                        key="entity_id",
                        value=item,
                        object_key=object_key,
                        section="actions",
                        span=span,
                        source="repeat_for_each",
                    )
                )

    # `wait_for_trigger`: a top-level LIST of trigger-shaped dicts (a single
    # recorded action with no further per-item span of its own, see the
    # module docstring), the one nested container in *trigger* position.
    for nested in as_dict_list(block.get("wait_for_trigger")):
        refs.extend(_walk_block(nested, object_key=object_key, section="triggers", span=span))

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
    # Modern HA device triggers/actions store ENTITY REGISTRY UUIDs (32-hex)
    # in their entity_id field, not domain.object_id names (owner field
    # evidence, 2026-07-05). Those are not entity-name references; drop them
    # here, at the single exit, rather than plumbing Optionals through every
    # _make_ref call site.
    return [
        r
        for r in refs
        if not (r.entity_id is not None and _REGISTRY_UUID_RE.fullmatch(r.entity_id))
    ]


def _spans_for_object(
    result: CompileResult, obj: IRObject, section: str, *, block_count: int
) -> list[SourceSpan | None]:
    """Per-index span lookup (parallel to the block list) via the public
    per-item accessor (``CompileResult.span_at``, M3 addition to bundle.py).
    """
    return [result.span_at(obj, section, i) for i in range(block_count)]
