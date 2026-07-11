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

**Annotation-truth pass (task #28):** every generated ``<Domain>Entity`` class
now inherits ``str`` -- matching the REAL runtime type (verified in
``hassle/compiler/helpers.py``: every entity reference the DSL hands back,
whether from a helper declaration or ``hassle.registry.entities``, is an
:class:`~hassle.compiler.helpers.EntityRef`, itself a ``str`` subclass). Before
this, a real decompiled bundle's ``state(e.binary_sensor.hall_motion)`` was a
**pyright error** even though it is correct, runnable HA-equivalent code: the
stub's ``BinarySensorEntity`` had no relationship to ``str`` at all, so it
failed every ``str``-typed (or ``str | list[str]``-typed) parameter pyright
checked it against. See ``hassle.compiler.builders``/``hassle.compiler.triggers``/
``hassle.compiler.purpose`` for the matching ``Sequence[str]``/``Sequence[...]``
widening this pass also applies to invariant ``list[...]``-typed parameters
(a *second*, independent reason a decompiled bundle used to fail pyright: a
list of ``EntityRef``/entity-class values is never assignable to an
invariant ``list[str]``-typed parameter, even once every element type is
itself ``str``-compatible).
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

# Selector-aware typing (coordinator hardening, M18 round): real HA
# `get_services` field schemas mostly describe a field's shape via
# `selector: {<selector_type>: {...}}` (docs/ha-api-notes.md §6), not a flat
# `type:` string -- `field.type` is `None` for most real captures. Mapping
# the selector's own key to a safe, always-resolvable Python annotation
# (never the bare selector-type word itself, which is not a real Python name)
# gives these fields a better type than the generic `str` fallback where a
# safe, more specific one is known; anything NOT in this map still falls back
# to `str` (or `dict[str, Any] | str` when the selector's own value shape is
# genuinely a mapping, e.g. `location`/`target`/`object`) -- see
# :func:`_field_type`.
_SELECTOR_PY_TYPE = {
    "boolean": "bool",
    "number": "float",
    "text": "str",
    "select": "str",
    "time": "str",
    "date": "str",
    "datetime": "str",
    "duration": "dict[str, Any]",
    "color_rgb": "list[int]",
    "color_temp": "int",
    # Location/target-ish selectors: HA stores these as a dict of named
    # fields (e.g. `{"latitude": ..., "longitude": ..., "radius": ...}`) --
    # never a scalar, and never a type named after the selector itself.
    "location": "dict[str, Any]",
    "target": "dict[str, Any]",
    "object": "dict[str, Any]",
    "action": "dict[str, Any]",
    "entity": "str",
    "device": "str",
    "area": "str",
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


def _field_type(field_type: str | None, *, selector: dict[str, object] | None = None) -> str:
    """Resolve a service field's HA schema type to a safe, ALWAYS-resolvable
    Python annotation -- either from a flat legacy ``type:`` string
    (``_PY_TYPE``) or, when absent (the common real-HA shape,
    docs/ha-api-notes.md §6: ``selector: {<selector_type>: {...}}``), from
    the selector's own key (``_SELECTOR_PY_TYPE``). Falls back to plain
    ``str`` for anything neither map recognizes -- NEVER the raw, unmapped
    type/selector-type word itself, which is not a real Python name and would
    make the generated stub reference an undefined identifier (coordinator-
    flagged regression, M18 round: a `location` selector previously leaked
    through unmapped)."""
    py = _PY_TYPE.get(field_type or "")
    if py is not None:
        if py == "str":
            return "str"
        return f"{py} | str"

    if selector:
        (selector_type,) = list(selector)[:1] or (None,)
        mapped = _SELECTOR_PY_TYPE.get(selector_type or "")
        if mapped is not None:
            if mapped in ("str", "dict[str, Any]"):
                return mapped
            return f"{mapped} | str"

    return "str"


#: HA's universal service-call envelope kwargs (owner field report,
#: BrandtCamp prettify pass): every decompiled call carries `metadata={}`
#: verbatim from stored config, and response-capable services take
#: `response_variable=`. These are call-envelope keys, not per-service
#: fields, so the snapshot's field list never includes them -- without
#: them here, every real decompiled bundle lights up with
#: reportCallIssue "No parameter named 'metadata'".
_ENVELOPE_PARAMS = [
    "metadata: dict[str, Any] = ...",
    "response_variable: str = ...",
    "alias: str = ...",
    "enabled: bool = ...",
    "continue_on_error: bool = ...",
]


def _envelope_params(service_def: ServiceDef) -> list[str]:
    """Envelope params minus any name a per-service field already claims --
    a duplicate parameter would make the generated ``.pyi`` a syntax error
    (nothing in HA's schema forbids a data key literally named ``enabled``;
    the service's own field wins, since it carries the snapshot's type)."""
    return [p for p in _ENVELOPE_PARAMS if p.split(":")[0] not in service_def.fields]


def _service_method(service_name: str, service_def: ServiceDef) -> list[str]:
    params = ["self"]
    for field_name, field in sorted(service_def.fields.items()):
        py_type = _field_type(field.type, selector=field.selector)
        params.append(f"{field_name}: {py_type} = ...")
    params.extend(_envelope_params(service_def))
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


def _service_function(service_name: str, service_def: ServiceDef) -> list[str]:
    """Same shape as :func:`_service_method` but as a ``@staticmethod`` --
    a domain namespace attribute (``light.turn_on(...)``) is called directly
    on the module-level instance, never through an actual ``self`` (there is
    no instance at all at runtime, `hassle.services._ServiceDomain` -- the
    stub models the call signature pyright checks against, and a plain
    (non-static) method's first parameter would otherwise be mistaken for
    ``self``, MILESTONES M18).

    **Annotation-truth pass (task #28):** unlike the entity-bound form
    (:func:`_service_method`, called as ``e.<domain>.<id>.<service>(...)``,
    where the target entity is implicit -- see
    ``hassle.compiler.helpers._EntityServiceMethod.__call__``), the namespace
    form (``hassle.services.<domain>.<service>(...)``) has NO implicit target
    at all: it delegates straight to ``hassle.compiler.actions.service``,
    whose ``target=`` is a real, commonly-passed keyword
    (`docs/dsl-f3.md`/DESIGN §5.3's "target= also accepts the bare entity
    target sugar"). The generated stub previously had no ``target`` parameter
    whatsoever, so every decompiled ``<domain>.<service>(target=..., ...)``
    call -- the decompiler's own canonical namespace-form output, MILESTONES
    M18 -- was a hard pyright ``reportCallIssue`` ("No parameter named
    'target'") in a real bundle. Typed the same permissive way
    ``normalize_target`` actually accepts (a bare entity ref/string, a
    sequence of them, or an already-built target dict) -- never the
    non-public ``AreaTarget``/``FloorTarget``/``LabelTarget``/``DeviceIdTarget``
    helper-return types, which are internal (not part of ``hassle.__all__``,
    docs/dsl-f3.md) and would make the generated stub reference an
    unimportable name."""
    params: list[str] = ["target: str | Sequence[str] | dict[str, Any] = ..."]
    for field_name, field in sorted(service_def.fields.items()):
        py_type = _field_type(field.type, selector=field.selector)
        params.append(f"{field_name}: {py_type} = ...")
    params.extend(_envelope_params(service_def))
    joined = ", ".join(params)
    one_line = f"    def {service_name}({joined}) -> None: ..."
    if len(one_line) <= 100 - 4:  # account for the `@staticmethod` line above it
        return ["    @staticmethod", one_line]
    lines = ["    @staticmethod", f"    def {service_name}("]
    for param in params:
        lines.append(f"        {param},")
    lines.append("    ) -> None: ...")
    return lines


def _services_domain_class_name(domain: str) -> str:
    """``light`` -> ``_LightServices`` (distinct from the entities stub's
    ``_Light`` domain-accessor name -- both stubs can be generated into the
    same ``typings/hassle/`` tree without a class-name collision)."""
    return "_" + "".join(part.capitalize() for part in domain.split("_")) + "Services"


def generate_services_stub(snapshot: RegistrySnapshot) -> str:
    """Generate ``hassle/services.pyi`` content from a registry snapshot
    (MILESTONES M18): a module-level ``__getattr__`` fallback (typed as
    returning the first domain's namespace class -- matching the entities
    stub's own ``_EntitiesRegistry.__getattr__`` convention, and keeping an
    unlisted/future domain from becoming a hard pyright error) plus one typed
    module-level attribute per known domain, each a namespace object exposing
    every one of that domain's services as a typed function.

    Reuses :func:`_service_method`'s field-typing logic (via
    :func:`_service_function`, its self-less sibling) so the two stubs can
    never disagree about how a service's fields are typed.
    """
    domains = sorted(snapshot.services)

    body: list[str] = []
    if not domains:
        # No services captured at all -- an empty, still-valid module (the
        # module-level __getattr__ fallback still makes every domain resolve
        # to *something*, just untyped `Any`-shaped calls). The trailing
        # `# pyright: ignore[reportIncompleteStub]` (N1, reviewer non-
        # blocking note): a bare module-level `__getattr__` trips pyright's
        # "obscures type errors for module" heuristic -- unlike the entities
        # stub's `_EntitiesRegistry.__getattr__` (a CLASS method on a module-
        # level VARIABLE), `hassle.services` is a REAL module at runtime, so
        # that class-indirection trick doesn't apply here without breaking
        # the direct `from hassle.services import light` import shape.
        # Explicitly suppressed rather than silently accepting the warning.
        body.append(
            "def __getattr__(name: str) -> Any: ...  # pyright: ignore[reportIncompleteStub]"
        )
        body.append("")
    else:
        prev_was_empty = False
        for domain in domains:
            class_name = _services_domain_class_name(domain)
            services = snapshot.services[domain]
            method_lines: list[str] = []
            for service_name in sorted(services):
                method_lines.extend(_service_function(service_name, services[service_name]))
            if method_lines:
                if body and body[-1] != "":
                    body.append("")
                body.append(f"class {class_name}:")
                body.extend(method_lines)
                body.append("")
                prev_was_empty = False
            else:
                if not prev_was_empty and body and body[-1] != "":
                    body.append("")
                body.append(f"class {class_name}: ...")
                prev_was_empty = True
        if body and body[-1] != "":
            body.append("")

        first_domain_class = _services_domain_class_name(domains[0])
        for domain in domains:
            body.append(f"{domain}: {_services_domain_class_name(domain)}")
        body.append("")
        # N1: see the domain-less branch's matching comment above -- same
        # explicit, targeted suppression, same reason.
        body.append(
            f"def __getattr__(name: str) -> {first_domain_class}: ...  "
            "# pyright: ignore[reportIncompleteStub]"
        )
        body.append("")

    body_text = "\n".join(body)
    header = [
        '"""Generated by `hassle stubs` from the registry snapshot. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    # `Sequence`/`Any` share ONE stdlib import block (ruff/isort's own
    # grouping: `collections.abc` and `typing` are both stdlib, so there is
    # no blank line between them -- only before the block and after it,
    # verified against actual `ruff check --select I001` output on this
    # generator's content). `Sequence` is only needed when at least one
    # domain actually rendered a `target=` parameter (task #28: every real
    # service function gets one; the domain-less `__getattr__`-only fallback
    # body never does); `Any` is needed for that same `target=` parameter, a
    # selector-typed field (`_SELECTOR_PY_TYPE`'s `dict[str, Any]` entries),
    # or the domain-less fallback's `Any` return type -- never an unused
    # import otherwise.
    stdlib_imports: list[str] = []
    if "Sequence" in body_text:
        stdlib_imports.append("from collections.abc import Sequence")
    if "Any" in body_text:
        stdlib_imports.append("from typing import Any")
    if stdlib_imports:
        header.extend(stdlib_imports)
        header.append("")
    return "\n".join(header) + "\n" + body_text


def generate_entities_stub(snapshot: RegistrySnapshot) -> str:
    """Generate ``entities.pyi`` content from a registry snapshot."""
    domains: dict[str, list[str]] = {}
    for entity in snapshot.entities:
        domain, _, object_id = entity.entity_id.partition(".")
        domains.setdefault(domain, []).append(object_id)

    lines: list[str] = []

    # --- one typed entity class per domain, with typed service methods ------
    # Every entity class now ALWAYS has at least one member (the `.state`
    # accessor, M20 entity-first conditions), so the previous "empty class
    # collapses to `class X: ...` on one line" convention no longer applies to
    # ANY domain -- there is no longer such a thing as a member-less entity
    # class. `state` is typed `Any` (not the real, non-public
    # `hassle.compiler.builders._StateAccessor`) -- same "widen rather than
    # leak an internal type into a generated stub" convention this module's
    # own docstring already documents for `Template`/service-field typing:
    # the accessor's exact operator-overload return types (`_StateAccessor`
    # for `>`/`<`, `_StateComparisonExpr` for `==`/`!=`, ...) are internal and
    # not part of `hassle.__all__`, so re-deriving them precisely here would
    # either leak a private name or drift the moment those internals change.
    # `Any` still resolves `.state`/`.state == ...`/`.state.in_([...])`
    # without a single false `reportAttributeAccessIssue` -- the actual gate
    # this stub exists to satisfy (M28's decompiled-bundle pyright gate).
    for domain in sorted(domains):
        entity_type = _entity_type_name(domain)
        services = snapshot.services.get(domain, {})
        method_lines: list[str] = []
        for service_name in sorted(services):
            method_lines.extend(_service_method(service_name, services[service_name]))
        if lines and lines[-1] != "":
            lines.append("")
        lines.append(f"class {entity_type}(str):")
        lines.append("    @property")
        lines.append("    def state(self) -> Any: ...")
        lines.extend(method_lines)
        lines.append("")
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

    body_text = "\n".join(lines)
    header = [
        '"""Generated by `hassle stubs` from the registry snapshot. Do not edit by hand."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    # `Any` only needed (and only imported) when a selector-typed field
    # actually rendered to it -- see `generate_services_stub`'s matching note.
    if "Any" in body_text:
        header.append("from typing import Any")
        header.append("")
    return "\n".join(header) + "\n" + body_text


_UNSET = object()


def _isort_all_sort_key(name: str) -> tuple[int, str]:
    """Sort key matching ruff's `RUF022` ("unsorted __all__", isort
    convention): `ALL_CAPS` constants first, then `PascalCase` classes, then
    everything else -- alphabetical within each group. Verified against
    `ruff check --select RUF022 --fix` on the actual generated content
    (`hassle.__all__`'s real name set) rather than assumed; needed so this
    generator's output is `ruff check`-clean without shelling out to ruff at
    generation time (matching `generate_entities_stub`/`generate_services_
    stub`'s own no-ruff-at-generation-time convention).

    Case-SENSITIVE within each group (`RUF022`'s own tie-break, verified: it
    orders `InOperatorTrapError` before `InclusiveNumericBoundError` -- plain
    codepoint order, `O` < `c`). This is the `__all__`-LIST convention only;
    ruff's `I001` (import-statement sorting, a DIFFERENT rule) uses a
    case-INSENSITIVE tie-break instead -- see :func:`_isort_import_sort_key`,
    used for the import-line block above the `__all__` list, never this one.
    """
    is_constant = name.replace("_", "").isupper() and any(c.isalpha() for c in name)
    is_class = name[:1].isupper() and not is_constant
    category = 0 if is_constant else (1 if is_class else 2)
    return (category, name)


def _isort_import_sort_key(name: str) -> tuple[int, str]:
    """Sort key for ONE `from module import name as name` re-export line
    (ruff's `I001`, isort convention) -- same category bucketing as
    :func:`_isort_all_sort_key` (`ALL_CAPS` constants first, then classes,
    then everything else), but CASE-INSENSITIVE within each bucket.

    Found the hard way (M20, entity-first conditions milestone): the two
    conventions genuinely differ. `RUF022`'s `__all__`-list sort is case-
    SENSITIVE (`InOperatorTrapError` before `InclusiveNumericBoundError`,
    `O` < `c`), but `I001`'s import-statement sort is case-INSENSITIVE
    (`InclusiveNumericBoundError` before `InOperatorTrapError`, `c` < `o`
    case-folded) -- verified against actual `ruff check --select I001 --fix`
    output on both orderings. Every name pair before this milestone happened
    to sort identically either way, so this divergence was latent until
    `InOperatorTrapError`/`InclusiveNumericBoundError` landed adjacent to
    each other in the same module's import block.
    """
    is_constant = name.replace("_", "").isupper() and any(c.isalpha() for c in name)
    is_class = name[:1].isupper() and not is_constant
    category = 0 if is_constant else (1 if is_class else 2)
    return (category, name.lower())


def _resolve_binding_module(hassle_pkg: object, name: str) -> str:
    """The module a ``hassle.__all__`` name should be re-exported FROM
    (reviewer finding B1): NOT ``getattr(obj, "__module__", ...)`` -- that
    reports the defining CLASS's module, which is wrong whenever ``obj`` is
    an INSTANCE built somewhere else. ``hassle.E_``/``PI``/``TAU`` are
    ``TemplateExpr`` instances constructed in ``hassle.compiler.math_expr``,
    but ``TemplateExpr`` the class lives in ``hassle.compiler.templates`` --
    ``__module__`` names the latter, which does not define ``E_`` at all
    (``from hassle.compiler.templates import E_`` is an unimportable line;
    pyright reports it as an unknown import symbol, and pyright/Pylance
    alike lose all typing for these three names in every generated bundle).

    Fix (adopted from reviewer direction): resolve the true BINDING module by
    provenance instead -- walk every already-imported ``hassle.*`` submodule
    (``sys.modules``, which already has every relevant submodule loaded,
    since importing top-level ``hassle`` transitively imports all of
    ``hassle.compiler.*``) and collect every module whose own namespace binds
    this exact object under this exact name (``getattr(module, name, ...) is
    obj`` -- identity, not equality, so a coincidentally-equal-but-different
    object in an unrelated module is never mistaken for the real binding).

    **Tie-break (deterministic, R8):** more than one module can legitimately
    bind the same name to the same object -- every frozen name is ALSO
    re-exported through the ``hassle.compiler`` barrel package
    (``hassle/compiler/__init__.py``'s own aggregating imports), so a name
    defined in ``hassle.compiler.math_expr`` binds under both
    ``hassle.compiler`` and ``hassle.compiler.math_expr``. The DEEPEST module
    (the most dot-separated segments) is preferred -- the barrel/aggregator
    is, by construction, never deeper than the module that actually defines
    the name, so this reliably picks the true defining module over any
    re-exporting barrel; ties at equal depth (never observed in practice, but
    handled for robustness) break alphabetically for full determinism.
    Falls back to ``"hassle"`` itself if no ``hassle.*`` submodule binds the
    name at all (should not happen for anything in ``hassle.__all__``, but
    never crashes the generator if it somehow did).
    """
    import sys

    obj = getattr(hassle_pkg, name)
    candidates: list[str] = []
    for module_name, module in sys.modules.items():
        # By the time this runs, top-level `hassle` (and therefore every
        # `hassle.compiler.*` submodule it transitively imports) has already
        # fully imported -- `sys.modules["hassle...*"]` is never a `None`
        # placeholder (that only arises mid-circular-import, which cannot be
        # the case for an already-fully-loaded package).
        if module_name != "hassle" and not module_name.startswith("hassle."):
            continue
        if getattr(module, name, _UNSET) is obj:
            candidates.append(module_name)
    if not candidates:
        return "hassle"
    candidates.sort(key=lambda m: (-m.count("."), m))
    return candidates[0]


def generate_hassle_reexport_stub() -> str:
    """Generate ``typings/hassle/__init__.pyi``: a re-export of every
    ``hassle.__all__`` name from its TRUE defining module (coordinator
    hardening, M18 round; binding-module resolution fixed per reviewer
    finding B1 -- see :func:`_resolve_binding_module`).

    A ``typings/hassle/`` stub directory containing ONLY submodule stubs
    (``registry/__init__.pyi``, ``services.pyi``) with no top-level
    ``typings/hassle/__init__.pyi`` risks pyright treating ``hassle`` itself
    as a namespace/partial stub package for that dotted path -- silently
    hiding the REAL installed package's own top-level surface (every
    ``from hassle import *`` name) in a bundle file. Always generating this
    file alongside the other two stubs means pyright's ``stubPath`` override
    carries the FULL top-level surface itself, regardless of how it resolves
    partial-stub-package fallback for any given pyright version/configuration.

    Grouped and sorted by defining module (``hassle.compiler.*`` throughout)
    so this is deterministic (R8) and immune to ``hassle.__all__``'s (or a
    dict's) iteration order -- and immune to ``hassle.compiler.__init__`` and
    ``hassle.__all__`` ever drifting apart, since it reads each name's ACTUAL
    runtime-resolved binding module rather than assuming one.
    """
    import hassle

    by_module: dict[str, list[str]] = {}
    for name in hassle.__all__:
        module = _resolve_binding_module(hassle, name)
        by_module.setdefault(module, []).append(name)

    lines: list[str] = [
        '"""Generated by `hassle stubs` from `hassle.__all__`. Do not edit by hand.',
        "",
        "Re-exports every frozen DSL name from its true defining module so pyright",
        "never treats `hassle` as a namespace/partial stub package once a submodule",
        'stub (`hassle/registry/__init__.pyi`, `hassle/services.pyi`) exists."""',
        "",
        "from __future__ import annotations",
        "",
    ]
    for module in sorted(by_module):
        # ONE `from module import name as name` statement per name (verified
        # against `ruff check --select I001` on the actual generated
        # content): ruff's isort treats the `X as X` explicit-reexport idiom
        # (PEP 484's convention for a stub that re-exports a name) as its own
        # logical import to sort, and always wants it split one-per-line --
        # a combined `from module import a as a, b as b` is never isort-clean
        # for this idiom, regardless of internal ordering.
        names = sorted(by_module[module], key=_isort_import_sort_key)
        for name in names:
            one_line = f"from {module} import {name} as {name}"
            if len(one_line) <= 100:
                lines.append(one_line)
            else:
                # ruff-format's own wrap for a re-export line that overflows
                # the line-length limit (verified against actual generated
                # content, e.g. `DanglingTemplateHelperDeclarationError`).
                lines.append(f"from {module} import (")
                lines.append(f"    {name} as {name},")
                lines.append(")")
    lines.append("")
    # Wrapped one name per line (ruff-format's own preference once a literal
    # exceeds the line-length limit, matching the import blocks above) --
    # `hassle.__all__` is long enough that a single-line `__all__ = [...]`
    # is never ruff-format-clean. Sorted via `_isort_all_sort_key` (ruff's
    # `RUF022`/isort convention: ALL_CAPS constants first, then PascalCase
    # classes, then everything else, alphabetical within each group) so a
    # downstream `ruff check`/`ruff format` over the generated `typings/`
    # tree (this file is real, checked-in-adjacent Python, not exempt from
    # either) never wants to reorder it.
    lines.append("__all__ = [")
    for name in sorted(hassle.__all__, key=_isort_all_sort_key):
        # `_format_str_literal` (double-quote-preferring, matches ruff
        # format's own quote style) rather than `!r` (always single-quoted)
        # -- every name here is a plain identifier so this is just the
        # quote-STYLE choice, never an escaping concern.
        lines.append(f"    {_format_str_literal(name)},")
    lines.append("]")
    lines.append("")
    return "\n".join(lines)
