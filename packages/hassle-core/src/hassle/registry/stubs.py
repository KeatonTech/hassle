"""The `.pyi` stub generator (DESIGN §5.2, MILESTONES M3 test 5).

Generates typed domain classes + per-entity typed attributes matching the
`hassle.registry.entities` attribute/index shape (docs/dsl-f3.md), so a bad
attribute name becomes a pyright error, and typed service methods from
`get_services` schemas.

Digit-leading object_ids (`sensor.3d_printer`) get the underscore-prefix
attribute name (`_3d_printer`) plus an attribute docstring naming the real
entity_id, and every domain class also supports `__getitem__` indexing so
`e.sensor["3d_printer"]` still works (the universal escape hatch, DESIGN §5.2).

**ux/stub-docstrings:** each entity attribute's friendly name used to be a
trailing `# comment` -- invisible to Pylance, which only surfaces docstrings
on hover and in the completion documentation pane. It is now an attribute
docstring: a string-literal statement immediately following the attribute
declaration (`entity_name -- entity_id (area: Area Name)`), which pyright and
Pylance both recognize as documentation for that attribute.

**ux/stub-device-names:** `has_entity_name` integrations (Matter and others)
routinely leave BOTH `entity.name` and `entity.original_name` null -- the
friendly name lives on the DEVICE instead. `_entity_display_name` mirrors
HA's own name composition (`homeassistant.helpers.entity.Entity.name`/
device_registry's `name_by_user or name`), best-effort, in this order:
1. `entity.name` (user override) -- unchanged;
2. else, if `entity.device_id` resolves against `snapshot.devices`:
   `device_name + (" " + original_name if original_name else "")`, where
   `device_name` is the device's `name_by_user` (user override) if set, else
   its `name`;
3. else `entity.original_name`;
4. else `entity.entity_id` -- and in that last case the docstring emits the
   entity_id ONCE (`"sensor.x"`), never the doubled `"sensor.x -- sensor.x"`
   form (a pre-existing wart, fixed regardless of which fallback rung is hit).

**Deviation from DESIGN's illustrative snippet:** DESIGN §5.2 shows
`LightEntity.turn_on(brightness_pct: int | Template = ..., transition: float =
...)`. There is no `Template` type anywhere in this codebase (verified: only
`TemplateExpr`, an internal, non-public builder class per docs/dsl-f3.md) --
using it in a *public* generated stub would require exporting an internal
name. This generator instead widens numeric/bool fields to also accept `str`
(the shape a Jinja template string renders as at the type level, since HA
accepts a template string wherever it accepts the field's native type) --
e.g. `brightness_pct: int | str = ...` -- documented here rather than
introducing a new public type as part of an unrelated milestone.
"""

from __future__ import annotations

from hassle.registry.snapshot import DeviceInfo, EntityInfo, RegistrySnapshot, ServiceDef

_PY_TYPE = {
    "integer": "int",
    "int": "int",
    "float": "float",
    "number": "float",
    "string": "str",
    "str": "str",
    "boolean": "bool",
    "bool": "bool",
}


def _domain_class_name(domain: str) -> str:
    """``light`` -> ``_Light``, ``binary_sensor`` -> ``_BinarySensor``."""
    return "_" + "".join(part.capitalize() for part in domain.split("_"))


def _entity_type_name(domain: str) -> str:
    """``light`` -> ``LightEntity``, ``binary_sensor`` -> ``BinarySensorEntity``."""
    return "".join(part.capitalize() for part in domain.split("_")) + "Entity"


def _attr_name(object_id: str) -> str:
    """Digit-leading object_ids get a single underscore prefix (DESIGN §5.2)."""
    if object_id and object_id[0].isdigit():
        return f"_{object_id}"
    return object_id


def _format_str_literal(text: str) -> str:
    """Render ``text`` as a ruff-format-clean Python string literal.

    Matches `ruff format`'s (Black-derived) quote preference exactly: prefer
    double quotes; fall back to single quotes only when the text contains a
    `"` and no `'` (avoids an otherwise-unnecessary escape) -- verified
    against real `ruff format` output in
    `test_stub_is_ruff_format_clean`/the quote-preference experiments in this
    branch's PR description. Names are user data (can contain quotes,
    backslashes, newlines); this is a full literal-escaping pass, not a
    sanitizer, so the docstring never drops data and the `.pyi` always
    parses (I3-style "never drop data" applied to generated text).
    """
    has_double = '"' in text
    has_single = "'" in text
    quote = "'" if (has_double and not has_single) else '"'
    out: list[str] = []
    for ch in text:
        if ch == "\\":
            out.append("\\\\")
        elif ch == quote:
            out.append("\\" + quote)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        else:
            out.append(ch)
    return f"{quote}{''.join(out)}{quote}"


def _device_name(device: DeviceInfo) -> str | None:
    """HA's own device display-name rule: the user override
    (`name_by_user`) wins over the integration-reported `name`."""
    return device.name_by_user or device.name


def _device_for_entity(snapshot: RegistrySnapshot, entity: EntityInfo) -> DeviceInfo | None:
    if entity.device_id is None:
        return None
    for device in snapshot.devices:
        if device.device_id == entity.device_id:
            return device
    return None


def _entity_display_name(snapshot: RegistrySnapshot, entity: EntityInfo) -> str | None:
    """``entity.name`` (user override) -- unchanged; else, if a device
    resolves, HA's `has_entity_name` composition (device display name,
    optionally suffixed with `original_name` when the entity is one of
    several sub-entities on that device); else `entity.original_name`; else
    ``None`` (the caller falls back to the entity_id itself,
    ux/stub-device-names)."""
    if entity.name:
        return entity.name

    device = _device_for_entity(snapshot, entity)
    if device is not None:
        device_name = _device_name(device)
        if device_name:
            if entity.original_name:
                return f"{device_name} {entity.original_name}"
            return device_name

    return entity.original_name


def _area_name(snapshot: RegistrySnapshot, entity: EntityInfo) -> str | None:
    """The area display name for ``entity``, resolved via `area_id` ->
    `snapshot.areas`, or ``None`` if unset/unresolvable."""
    if entity.area_id is None:
        return None
    for area in snapshot.areas:
        if area.area_id == entity.area_id:
            return area.name
    return None


def _entity_docstring_line(snapshot: RegistrySnapshot, entity: EntityInfo) -> str:
    """Build the attribute-docstring line (indented, quoted, format-clean)
    for ``entity``: display name -- entity_id (area: Area Name) -- or, when
    no display name resolves at all (ux/stub-device-names), just the
    entity_id ONCE (never the doubled ``"entity_id -- entity_id"`` form).

    R7's >100-char fallback rule, adapted for docstrings: truncate/drop the
    area clause first, keeping the load-bearing display name + entity_id
    (needed for the digit-leading rule) intact; if the line is STILL over 100
    columns even without the area (an implausibly long display name -- device
    names can be long too), the display name itself is truncated with an
    ellipsis -- the entity_id is never shortened, since dropping it would
    leave a docstring documenting a different-looking entity."""
    display_name = _entity_display_name(snapshot, entity)
    area = _area_name(snapshot, entity)

    def _line(text: str) -> str:
        return f"    {_format_str_literal(text)}"

    if display_name is None:
        # No name resolved anywhere in the chain (entity.name, device, nor
        # original_name) -- the entity_id IS the display name here, so it
        # must appear only once, never doubled as "entity_id -- entity_id".
        return _line(entity.entity_id)

    if area:
        text = f"{display_name} -- {entity.entity_id} (area: {area})"
        line = _line(text)
        if len(line) <= 100:
            return line

    text = f"{display_name} -- {entity.entity_id}"
    line = _line(text)
    if len(line) <= 100:
        return line

    # Still too long without the area: truncate the display name (keep the
    # entity_id fully intact) until it fits. Shrunk one character at a time
    # against the fully-escaped rendered line (not the raw character count) --
    # escaping can expand length (e.g. a `"`-heavy name forced into
    # double-quote-with-escape mode), so a naive pre-escape character budget
    # can undershoot and still overflow 100 columns.
    suffix = f"... -- {entity.entity_id}"
    name_budget = len(display_name)
    while name_budget > 0:
        candidate = _line(f"{display_name[:name_budget]}{suffix}")
        if len(candidate) <= 100:
            return candidate
        name_budget -= 1
    return _line(suffix)


def _field_type(field_type: str | None) -> str:
    py = _PY_TYPE.get(field_type or "")
    if py is None:
        return "str"
    if py == "str":
        return "str"
    return f"{py} | str"


def _service_method(service_name: str, service_def: ServiceDef) -> list[str]:
    params = ["self"]
    for field_name, field in sorted(service_def.fields.items()):
        py_type = _field_type(field.type)
        params.append(f"{field_name}: {py_type} = ...")
    joined = ", ".join(params)
    one_line = f"    def {service_name}({joined}) -> None: ..."
    if len(one_line) <= 100:
        return [one_line]
    # Wrap one parameter per line (R7 line-length convention) rather than
    # overflow -- a generated stub with many typed fields (e.g. `light.turn_on`)
    # can easily exceed 100 columns on one line.
    lines = [f"    def {service_name}("]
    for param in params:
        lines.append(f"        {param},")
    lines.append("    ) -> None: ...")
    return lines


def generate_entities_stub(snapshot: RegistrySnapshot) -> str:
    """Generate ``entities.pyi`` content from a registry snapshot."""
    domains: dict[str, list[str]] = {}
    for entity in snapshot.entities:
        domain, _, object_id = entity.entity_id.partition(".")
        domains.setdefault(domain, []).append(object_id)

    lines: list[str] = [
        '"""Generated by `hassle stubs` from the registry snapshot. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
    ]

    # --- one typed entity class per domain, with typed service methods ------
    # Matches `ruff format`'s `.pyi`-aware style: an empty class collapses to
    # `class X: ...` on one line with no blank line before the next empty
    # class, so the generated golden is format-clean without shelling out to
    # ruff at generation time.
    prev_was_empty = False
    for domain in sorted(domains):
        entity_type = _entity_type_name(domain)
        services = snapshot.services.get(domain, {})
        method_lines: list[str] = []
        for service_name in sorted(services):
            method_lines.extend(_service_method(service_name, services[service_name]))
        if method_lines:
            if lines and lines[-1] != "":
                lines.append("")
            lines.append(f"class {entity_type}:")
            lines.extend(method_lines)
            lines.append("")
            prev_was_empty = False
        else:
            if not prev_was_empty and lines and lines[-1] != "":
                lines.append("")
            lines.append(f"class {entity_type}: ...")
            prev_was_empty = True
    if lines and lines[-1] != "":
        lines.append("")

    # --- one domain accessor class per domain, attribute + index access -----
    for domain in sorted(domains):
        class_name = _domain_class_name(domain)
        entity_type = _entity_type_name(domain)
        object_ids = sorted(domains[domain])
        lines.append(f"class {class_name}:")
        for object_id in object_ids:
            attr = _attr_name(object_id)
            entity = next(e for e in snapshot.entities if e.entity_id == f"{domain}.{object_id}")
            lines.append(f"    {attr}: {entity_type}")
            lines.append(_entity_docstring_line(snapshot, entity))
        lines.append(f"    def __getitem__(self, object_id: str) -> {entity_type}: ...")
        lines.append("")

    # --- the `entities` accessor itself --------------------------------------
    first_domain_class = _domain_class_name(sorted(domains)[0])
    lines.append("class _EntitiesRegistry:")
    for domain in sorted(domains):
        lines.append(f"    {domain}: {_domain_class_name(domain)}")
    lines.append(f"    def __getattr__(self, domain: str) -> {first_domain_class}: ...")
    lines.append("")
    lines.append("entities: _EntitiesRegistry")
    lines.append("")

    return "\n".join(lines)
