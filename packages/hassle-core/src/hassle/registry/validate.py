"""The validator (DESIGN §9 tiers 1-3): `validate_bundle(compile_result,
snapshot) -> list[Finding]`.

Offline only (fixtures/registry snapshot); no network. Covers:
- unknown entity/area/floor/label/device references, including references
  nested inside if/choose/repeat/parallel/wait_for_trigger action containers
  (see `hassle.registry.extract`'s recursive descent)
- did-you-mean suggestions
- purpose-vocabulary validation + known-renames hints
- bundle-declared helpers counting as existing
- service-call parameter validation: unknown/wrong-type/missing-required

## Coverage boundaries (deliberate permissiveness; the agent-facing docs
generator sources this section, so keep it accurate)

Two rules are intentionally permissive rather than strict, both because the
IR shape this validator walks (`IRObject.to_ha()`) does not retain enough
information to tell "the user's mistake" apart from "a legitimate escape
hatch":

- **A service whose schema has an empty `fields: {}` is never checked for
  unknown/wrong-type params.** The registry snapshot's `services[domain]
  [service].fields` dict does not distinguish "this service genuinely takes
  no parameters" from "the schema capture is incomplete" -- both look like an
  empty dict. Treating empty-fields as "nothing enforceable" avoids flagging
  every real, intentional param on a service HA's `get_services` happens not
  to have fully described (`_validate_service_params`, the `not
  service_def.fields` guard).
- **A bare `entity_id=` kwarg to `service(...)` is never flagged as an
  "unknown service param."** HA's own legacy target-shorthand
  (`entity_id="light.x"` instead of `target={"entity_id": "light.x"}`) and an
  intentional service data field are merged into the exact same `data` dict
  by the compiler's `ServiceAction` builder with no residual marker of which
  one it started as -- so `entity_id` is unconditionally exempted from the
  unknown-param check regardless of the service (`_validate_service_params`,
  the `param_name == "entity_id"` guard). The entity_id *value* itself is
  still validated as a normal entity reference by `_validate_references`;
  only the "is `entity_id` a recognized field of this service" question is
  skipped.

Everything else this module checks is strict: an unrecognized entity/area/
floor/label/device id, purpose-vocabulary type, or (non-empty-schema)
service param always produces a Finding.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from hassle.compiler.bundle import CompileResult
from hassle.compiler.spans import SourceSpan
from hassle.ir import slugify
from hassle.ir.keys import GROUP_DOMAINS, category_shaped_stem, humanize_slug
from hassle.ir.models import HelperConfig
from hassle.registry.didyoumean import did_you_mean
from hassle.registry.extract import as_dict_list, extract_references
from hassle.registry.finding import Finding
from hassle.registry.renames import PURPOSE_RENAMES
from hassle.registry.snapshot import RegistrySnapshot

_TYPE_KEY = {"triggers": "trigger", "conditions": "condition"}


def _where(span: SourceSpan | None) -> tuple[str | None, int | None]:
    if span is None:
        return None, None
    return span.file, span.line


#: Template-helper object kinds -> the REAL entity domain the created
#: config entry produces (template_binary_sensor:x -> binary_sensor.x).
_TEMPLATE_ENTITY_DOMAIN = {
    "template_sensor": "sensor",
    "template_binary_sensor": "binary_sensor",
    "template_number": "number",
    "template_select": "select",
}

#: Group-helper object kinds -> the REAL entity domain the created config
#: entry produces (mirrors `_TEMPLATE_ENTITY_DOMAIN`): a group's own
#: flavor IS its entity domain by construction (`group_cover:x` ->
#: `cover.x`), so this is just the `"group_"` prefix stripped off each kind.
_GROUP_ENTITY_DOMAIN = {domain: domain[len("group_") :] for domain in GROUP_DOMAINS}


def _bundle_declared_keys(result: CompileResult) -> set[str]:
    """``"<domain>:<id>"`` keys for every object this bundle itself declares:
    helper domains plus automations/scripts (an automation referencing its
    own or a sibling automation/script entity, e.g. ``automation.turn_off``
    targeting itself, or a ``script.<id>`` call, counts as existing exactly
    like a bundle-declared helper).

    Template AND group helpers additionally register the ENTITY their config
    entry creates (`template_binary_sensor:x` also declares
    `binary_sensor:x`; `group_cover:x` also declares `cover:x`) -- an
    automation gating on the bundle's own fused template sensor (or a group
    nesting the bundle's own declared group) must not trip unknown-entity
    before the first push."""
    keys = set(result.objects)
    for key in result.objects:
        kind, _, object_id = key.partition(":")
        entity_domain = _TEMPLATE_ENTITY_DOMAIN.get(kind) or _GROUP_ENTITY_DOMAIN.get(kind)
        if entity_domain is not None:
            keys.add(f"{entity_domain}:{object_id}")
    return keys


#: Core entities that exist in every HA instance but never appear in the
#: entity REGISTRY (they predate it), so no registry snapshot can contain
#: them -- referencing them is always legitimate (a template reading
#: state_attr('sun.sun', 'elevation') must not fail validate).
_CORE_NON_REGISTRY_ENTITIES = frozenset({"sun.sun"})


def _check_entity(
    entity_id: str,
    *,
    snapshot: RegistrySnapshot,
    declared_helpers: set[str],
    file: str | None,
    line: int | None,
) -> Finding | None:
    if entity_id in _CORE_NON_REGISTRY_ENTITIES:
        return None
    if entity_id in snapshot.entity_ids():
        return None
    domain, _, object_id = entity_id.partition(".")
    if f"{domain}:{object_id}" in declared_helpers:
        return None
    suggestion = did_you_mean(entity_id, snapshot.entity_ids())
    fix = (
        f"Did you mean `{suggestion}`?"
        if suggestion is not None
        else "Check the entity id against your registry snapshot (`hassle stubs --refresh`), "
        "or declare it as a helper in this bundle if it should exist."
    )
    return Finding(
        code="unknown-entity",
        severity="error",
        file=file,
        line=line,
        message=f"`{entity_id}` is not a known entity in the registry snapshot.",
        fix=fix,
    )


def _check_id(
    value: str,
    *,
    known: set[str],
    kind: str,
    field_name: str,
    file: str | None,
    line: int | None,
) -> Finding | None:
    """Generic "is this id in the known set?" check for area/floor/label/device
    ids -- they all share the same shape (a Finding naming the field, a
    did-you-mean suggestion when close, else a generic hint).
    """
    if value in known:
        return None
    suggestion = did_you_mean(value, known)
    fix = (
        f"Did you mean `{suggestion}`?"
        if suggestion
        else f"Check the {field_name} against your registry snapshot."
    )
    return Finding(
        code=f"unknown-{kind}",
        severity="error",
        file=file,
        line=line,
        message=f"`{value}` is not a known {field_name} in the registry snapshot.",
        fix=fix,
    )


def _validate_references(result: CompileResult, snapshot: RegistrySnapshot) -> list[Finding]:
    findings: list[Finding] = []
    declared_helpers = _bundle_declared_keys(result)
    seen: set[tuple[str | None, str | None, str | None, int | None]] = set()
    for ref in extract_references(result):
        file, line = _where(ref.span)
        finding: Finding | None = None
        dedupe_key: tuple[str | None, str | None, str | None, int | None] | None = None
        if ref.entity_id is not None:
            dedupe_key = ("entity", ref.entity_id, file, line)
            if dedupe_key not in seen:
                finding = _check_entity(
                    ref.entity_id,
                    snapshot=snapshot,
                    declared_helpers=declared_helpers,
                    file=file,
                    line=line,
                )
        elif ref.area_id is not None:
            dedupe_key = ("area", ref.area_id, file, line)
            if dedupe_key not in seen:
                finding = _check_id(
                    ref.area_id,
                    known=snapshot.area_ids(),
                    kind="area",
                    field_name="area_id",
                    file=file,
                    line=line,
                )
        elif ref.floor_id is not None:
            dedupe_key = ("floor", ref.floor_id, file, line)
            if dedupe_key not in seen:
                finding = _check_id(
                    ref.floor_id,
                    known=snapshot.floor_ids(),
                    kind="floor",
                    field_name="floor_id",
                    file=file,
                    line=line,
                )
        elif ref.label_id is not None:
            dedupe_key = ("label", ref.label_id, file, line)
            if dedupe_key not in seen:
                finding = _check_id(
                    ref.label_id,
                    known=snapshot.label_ids(),
                    kind="label",
                    field_name="label_id",
                    file=file,
                    line=line,
                )
        elif ref.device_id is not None:
            dedupe_key = ("device", ref.device_id, file, line)
            if dedupe_key not in seen:
                finding = _check_id(
                    ref.device_id,
                    known=snapshot.device_ids(),
                    kind="device",
                    field_name="device_id",
                    file=file,
                    line=line,
                )
        if dedupe_key is not None:
            seen.add(dedupe_key)
        if finding is not None:
            findings.append(finding)
    return findings


def _validate_purpose_vocabulary(
    result: CompileResult, snapshot: RegistrySnapshot
) -> list[Finding]:
    findings: list[Finding] = []
    known_triggers = set(snapshot.purpose_vocabulary.triggers)
    known_conditions = set(snapshot.purpose_vocabulary.conditions)
    for obj in result.objects.values():
        body = obj.to_ha()
        for section, type_key in _TYPE_KEY.items():
            blocks = as_dict_list(body.get(section))
            known = known_triggers if section == "triggers" else known_conditions
            for i, block in enumerate(blocks):
                type_string_raw = block.get(type_key)
                if not isinstance(type_string_raw, str) or "." not in type_string_raw:
                    continue  # not a purpose type (classic types never contain a dot)
                type_string = type_string_raw
                span = result.span_at(obj, section, i)
                file, line = _where(span)
                if type_string in known:
                    continue
                if type_string in PURPOSE_RENAMES:
                    new_name = PURPOSE_RENAMES[type_string]
                    findings.append(
                        Finding(
                            code="renamed-purpose-type",
                            severity="error",
                            file=file,
                            line=line,
                            message=(
                                f"`{type_string}` is a pre-2026.7 purpose-vocabulary key that HA "
                                f"renamed without migration; it no longer works."
                            ),
                            fix=f"Use `{new_name}` instead.",
                        )
                    )
                else:
                    findings.append(
                        Finding(
                            code="unknown-purpose-type",
                            severity="error",
                            file=file,
                            line=line,
                            message=(
                                f"`{type_string}` is not a known purpose-{type_key} type in the "
                                f"registry snapshot's enumerated vocabulary."
                            ),
                            fix=(
                                "Check the spelling against `hassle stubs --refresh`'s enumerated "
                                "vocabulary, or refresh the registry snapshot if this is a newer "
                                "HA release."
                            ),
                        )
                    )
    return findings


_TYPE_MAP: dict[str, type[Any]] = {
    "integer": int,
    "int": int,
    "float": float,
    "number": float,
    "string": str,
    "str": str,
    "boolean": bool,
    "bool": bool,
}


def _matches_type(value: Any, type_name: str | None) -> bool:
    if type_name is None:
        return True
    expected = _TYPE_MAP.get(type_name)
    if expected is None:
        return True  # unknown/unenforceable schema type -> don't flag
    if isinstance(value, str) and "{{" in value:
        return True  # a runtime template can produce any type -> don't flag
    if expected is bool:
        return isinstance(value, bool)
    if expected is float:
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected is int:
        return isinstance(value, int) and not isinstance(value, bool)
    if expected is str:
        return isinstance(value, str)
    return True


def _validate_unknown_services(result: CompileResult, snapshot: RegistrySnapshot) -> list[Finding]:
    """An `{"action": "<domain>.<service>", ...}` that closely
    resembles (but does not exactly match) a real `domain.service` in the
    registry snapshot gets an `unknown-service` Finding naming the close match
    -- the namespace form (`hassle.services.<domain>.<service>(...)`) and the
    entity-method form (`e.<domain>.<id>.<service>(...)`) compile to the
    identical `{"action": ...}` IR shape as `service(...)`, so this check
    (like `_validate_service_params` below) is driven purely by that shape and
    fires identically for all three call forms.

    **Deliberately did-you-mean-gated, not "any unrecognized domain.service"**
    (verified against the fixture-corpus false-positive gate,
    `test_registry_validate.py::test_no_false_positives_on_golden_corpus`,
    which caught two successively broader designs as too aggressive): real HA
    services are not a stable, fully-enumerable set the way entities are.
    `notify.<device_slug>` is a per-device service HA registers dynamically
    per notify-capable integration (never in a static capture unless that
    exact device happens to be present when the snapshot was taken); a
    domain's static services can be under-captured by a particular
    `get_services` snapshot (added in a newer HA release, or an integration
    simply not loaded when the snapshot was taken -- `cover`/`scene`/`siren`/
    `weather`/`persistent_notification` all reproduced this against the
    fixture corpus's registry snapshot, which only enumerates the handful of
    domains its own entities span). None of that resembles an EXISTING
    `domain.service` string by edit distance, though -- a real typo (`ligth.
    turn_on`, `light.turn_of`) does. So: only flag when :func:`did_you_mean`
    actually finds a close match over every known `domain.service` string;
    silent otherwise (an entirely novel, correctly-spelled domain/service this
    snapshot never captured has no reason to resemble anything already known).
    This intentionally narrows "catch a typo" to cases with positive
    evidence of one, rather than flagging every gap in a schema capture that
    is inherently a snapshot-in-time, never a complete enumeration.

    Only checked when the snapshot actually has services data at all (an
    empty `snapshot.services` -- no registry snapshot pulled yet -- means
    "unknown" can't be distinguished from "not captured", so this check is
    silent rather than false-positiving on every service in the bundle).
    """
    if not snapshot.services:
        return []
    findings: list[Finding] = []
    known_pairs = {
        f"{domain}.{service_name}"
        for domain, services in snapshot.services.items()
        for service_name in services
    }
    for obj in result.objects.values():
        body = obj.to_ha()
        blocks = as_dict_list(body.get("actions"))
        for i, block in enumerate(blocks):
            action_raw = block.get("action")
            if not isinstance(action_raw, str) or "." not in action_raw:
                continue
            action = action_raw
            if "{{" in action:
                continue  # templated service name -- nothing literal to check
            if action in known_pairs:
                continue
            suggestion = did_you_mean(action, known_pairs)
            if suggestion is None:
                continue  # no close match -- likely a real, just-uncaptured domain/service
            span = result.span_at(obj, "actions", i)
            file, line = _where(span)
            fix = f"Did you mean `{suggestion}`?"
            findings.append(
                Finding(
                    code="unknown-service",
                    severity="error",
                    file=file,
                    line=line,
                    message=(
                        f"`{action}` is not a known service in the registry snapshot; it closely "
                        f"resembles `{suggestion}`."
                    ),
                    fix=fix,
                )
            )
    return findings


def _validate_service_params(result: CompileResult, snapshot: RegistrySnapshot) -> list[Finding]:
    findings: list[Finding] = []
    for obj in result.objects.values():
        body = obj.to_ha()
        blocks = as_dict_list(body.get("actions"))
        for i, block in enumerate(blocks):
            action_raw = block.get("action")
            if not isinstance(action_raw, str) or "." not in action_raw:
                continue
            action = action_raw
            domain, _, service_name = action.partition(".")
            if domain == "script" and f"script:{service_name}" in result.objects:
                # A script declared in THIS bundle: its local field list is
                # the truth. The snapshot's copy is the LAST PUSH's schema --
                # a freshly added field (e.g. a new flag on a locally edited
                # script) would false-positive as unknown. The local
                # declaration is already validated structurally at compile
                # time, so skip the stale-schema comparison entirely.
                continue
            service_def = snapshot.service_def(domain, service_name)
            if service_def is None or not service_def.fields:
                # No schema (or a deliberately empty/unenforced one) -> nothing to
                # validate against; skip rather than guess.
                continue
            span = result.span_at(obj, "actions", i)
            file, line = _where(span)
            data_raw = block.get("data")
            data: dict[str, Any] = (
                cast(dict[str, Any], data_raw) if isinstance(data_raw, dict) else {}
            )
            for param_name, value in data.items():
                if param_name == "entity_id":
                    # A bare `entity_id=` kwarg is HA's own legacy target shorthand
                    # (pre-`target:` addressing), not a service data field -- it is
                    # never part of a service's own field schema, so it is never
                    # "unknown" no matter which service this is.
                    continue
                field = service_def.fields.get(param_name)
                if field is None:
                    findings.append(
                        Finding(
                            code="unknown-service-param",
                            severity="error",
                            file=file,
                            line=line,
                            message=(
                                f"`{param_name}` is not a known parameter of `{action}` "
                                f"(fields: {', '.join(sorted(service_def.fields)) or '<none>'})."
                            ),
                            fix=f"Remove `{param_name}=` or correct its spelling.",
                        )
                    )
                    continue
                if not _matches_type(value, field.type):
                    article = "an" if (field.type or "")[:1] in "aeiou" else "a"
                    findings.append(
                        Finding(
                            code="service-param-wrong-type",
                            severity="error",
                            file=file,
                            line=line,
                            message=(
                                f"`{action}`'s `{param_name}` expects {article} {field.type} "
                                f"value, got {value!r} ({type(value).__name__})."
                            ),
                            fix=(
                                f"Pass {article} {field.type} value for `{param_name}` "
                                "(or a template string)."
                            ),
                        )
                    )
            missing = [
                name
                for name, field in service_def.fields.items()
                if field.required and name not in data
            ]
            for name in missing:
                findings.append(
                    Finding(
                        code="service-param-missing-required",
                        severity="error",
                        file=file,
                        line=line,
                        message=f"`{action}` is missing its required parameter `{name}`.",
                        fix=f"Pass `{name}=...` to this `service(...)` call.",
                    )
                )
    return findings


def _validate_helper_slugs(
    result: CompileResult,
    snapshot: RegistrySnapshot,
    adopted_helper_keys: frozenset[str] = frozenset(),
) -> list[Finding]:
    """docs/internals/ha-api-notes.md §17.5: a helper whose
    ``id=`` does not match ``slugify(name)`` will silently get a *different*
    identity from real HA's WS-API storage-collection ``create``, which
    derives the item id by slugifying ``name`` and ignores any caller-supplied
    ``id`` -- breaking the id<->entity mapping the bundle (and the sync
    engine's object keys) assume.

    Only checked when ``name`` is present (nothing to slugify against
    otherwise); a `HelperConfig` with no `name` set is not this validator's
    concern.

    **Helpers only -- do NOT generalize this to scripts or automations**
    (docs/internals/ha-api-notes.md §17.5). The rule is
    a property of HA's WS storage-collection ``create``, which really does
    derive the item id from ``slugify(name)``. Neither config-REST kind works
    that way: a script is stored under the object_id in its REST path
    (``/api/config/script/config/{object_id}``) and an automation under its
    intrinsic ``id`` field -- ``alias`` is only a friendly name for both. A
    field report of a pushed ``@script(id="dining_bid_manual",
    alias="Dining Bid: Manual Hold")`` landing as
    ``script.dining_bid_manual_hold`` looked like this rule generalizing, but
    the alias slug came from Hassle's own create path, not HA (fixed in
    `hassle.sync.apply._create_body`). A ``script-id-alias-mismatch`` Finding
    would therefore be *wrong advice on product surface*: it would tell
    owners to rename working entities, and for an adopted script it would ask
    them to change an existing object's HA id (invariant I2).

    **Scoped to NEW declarations (§17.5):** the slug-derivation rule is a
    property of the WS-API *creation* path -- it says nothing about a helper
    that already exists. A live registry's ``.storage`` can legitimately hold
    helpers created some other way (e.g. an external integration writing
    ``.storage`` directly) whose id does not equal ``slugify(name)``; those
    are adopted, already-live truth, and telling the user to "fix" the id
    would break the bundle's mapping to a real, pre-existing entity (an
    existing object's HA id is never changed). So: if
    ``<domain>.<supplied_id>`` is
    already present in the registry snapshot, this is an adopted helper, not
    a fresh `create` -- the slug rule never fires for it, so no Finding.

    If the snapshot itself is empty (no entities at all -- e.g. no
    `.hassle/registry.json` was ever pulled), we cannot distinguish "new" from
    "adopted" by lookup; keep firing (current behavior -- silence-by-default
    would hide a real new-declaration bug) but soften to a ``"note"``
    severity and say so in the fix, since we can't confirm this is new.
    """
    findings: list[Finding] = []
    known_entities = snapshot.entity_ids()
    snapshot_available = bool(snapshot.entities)
    for key, obj in result.objects.items():
        if not isinstance(obj, HelperConfig):
            continue
        name = obj.name
        if not isinstance(name, str) or not name:
            continue
        supplied_id = obj.identity
        if supplied_id is None:
            continue
        expected_id = slugify(name)
        if supplied_id == expected_id:
            continue
        # Manifest membership is the definitive "adopted" signal: entity-id
        # inference fails when the entity was renamed after creation (field
        # evidence: storage id front_bedroom_occupied, entity renamed after
        # the room became an office -- §17.5).
        if f"{obj.kind()}:{supplied_id}" in adopted_helper_keys:
            continue
        entity_id = f"{obj.kind()}.{supplied_id}"
        if entity_id in known_entities:
            # Adopted helper: this id already exists in HA under this exact
            # domain, so nothing will be freshly `create`d and the slug rule
            # does not apply -- it's live truth, not a new declaration.
            continue
        span = result.decl_span_for(key)
        file, line = _where(span)
        if snapshot_available:
            findings.append(
                Finding(
                    code="helper-id-name-mismatch",
                    severity="error",
                    file=file,
                    line=line,
                    message=(
                        f'Helper `{key}` declares `id="{supplied_id}"`, but `{entity_id}` is '
                        f"not in the registry snapshot -- Home Assistant will create it fresh "
                        f"via the WS API, which derives a new helper's real identity by "
                        f'slugifying its `name` ("{name}" -> `{expected_id}`), ignoring the '
                        f"supplied id."
                    ),
                    fix=(
                        f'Change `id="{supplied_id}"` to `id="{expected_id}"` (or rename the '
                        f"helper to a `name` that slugifies to `{supplied_id}`), so the bundle's "
                        f"id matches what HA will actually assign. (This only applies to new "
                        f"helpers Hassle creates; an already-existing helper with this id is "
                        f"exempt -- see docs/internals/ha-api-notes.md §17.5.)"
                    ),
                )
            )
        else:
            findings.append(
                Finding(
                    code="helper-id-name-mismatch",
                    severity="note",
                    file=file,
                    line=line,
                    message=(
                        f'Helper `{key}` declares `id="{supplied_id}"`, which does not match '
                        f'`slugify(name)` ("{name}" -> `{expected_id}`); if this is a NEW '
                        f"helper, Home Assistant's WS API will derive its real identity from "
                        f"the name slug and ignore the supplied id. No registry snapshot was "
                        f"available, so it's unknown whether `{entity_id}` already exists "
                        f"(in which case this would not apply -- see "
                        f"docs/internals/ha-api-notes.md "
                        f"§17.5)."
                    ),
                    fix=(
                        f'If this helper is new, change `id="{supplied_id}"` to '
                        f'`id="{expected_id}"` (or rename to a `name` that slugifies to '
                        f"`{supplied_id}`). Run `hassle pull` or `hassle stubs --refresh` to "
                        f"get a registry snapshot so this check can tell new from adopted."
                    ),
                )
            )
    return findings


def _validate_group_entities(result: CompileResult, snapshot: RegistrySnapshot) -> list[Finding]:
    """A group helper's own ``entities=`` member list
    is checked against the registry snapshot exactly like a trigger/
    condition/action ``entity_id`` reference -- a member that doesn't exist
    (declared bundle objects count as existing too, `_bundle_declared_keys`,
    so referencing a sibling helper the bundle itself declares, or another
    group nested inside this one, is never flagged) surfaces the standard
    ``unknown-entity`` Finding (file:line, fix).

    Unlike a trigger/condition/action reference, a group helper's own body is
    never walked by `hassle.registry.extract.extract_references` at all (that
    walker only descends into ``triggers``/``conditions``/``actions``
    sections -- a group/template helper's IR body has none of those) -- this
    is therefore new validation logic, not free reuse of that walker (template
    helpers have no analogous "list of entity ids" field to check)."""
    findings: list[Finding] = []
    declared_helpers = _bundle_declared_keys(result)
    for key, obj in result.objects.items():
        kind, _, _ = key.partition(":")
        if kind not in GROUP_DOMAINS:
            continue
        body = obj.to_ha()
        entities = body.get("entities")
        if not isinstance(entities, list):
            continue
        span = result.decl_span_for(key)
        file, line = _where(span)
        for entity_id in cast("list[Any]", entities):
            if not isinstance(entity_id, str):
                continue
            finding = _check_entity(
                entity_id,
                snapshot=snapshot,
                declared_helpers=declared_helpers,
                file=file,
                line=line,
            )
            if finding is not None:
                findings.append(finding)
    return findings


def _validate_category_globals(result: CompileResult) -> list[Finding]:
    """A bundle file's ``CATEGORY`` global must slugify to
    that file's own stem (the same anchor `bundle_ops._category_source_path`/
    push-side write-back use to match a category by name) -- a mismatch means
    the declared display name and the file's placement disagree about which
    category this is, which is unresolvable without guessing, so it's flagged
    rather than silently trusted either way. Never blocks the object itself
    from compiling/validating/applying (this check is isolated from the rest
    of validation) -- write-back separately ignores a mismatched global with
    its own warning (`hassle.sync.category_writeback`)."""
    findings: list[Finding] = []
    for source_path, category in result.category_globals.items():
        # For a CATEGORY PACKAGE module the anchor is the PACKAGE's name, not
        # the module's own stem: `automatic_hvac/climate.py` must slugify-match
        # `automatic_hvac`, exactly as a root-level `automatic_hvac.py` does.
        stem = (
            category_shaped_stem(source_path, package_roots=result.category_packages)
            or Path(source_path).stem
        )
        expected_slug = slugify(category.value)
        if expected_slug == stem:
            continue
        file = category.span.file if category.span is not None else source_path
        line = category.span.line if category.span is not None else None
        findings.append(
            Finding(
                code="category-slug-mismatch",
                severity="error",
                file=file,
                line=line,
                message=(
                    f'`CATEGORY = "{category.value}"` in `{source_path}` does not slugify to '
                    f'this file\'s own name -- `slugify("{category.value}")` is '
                    f"`{expected_slug}`, but the file is named `{stem}.py`."
                ),
                fix=(
                    f"Rename the file to `{expected_slug}.py` (or change `CATEGORY` to a name "
                    f"that slugifies to `{stem}`, e.g. a display name close to "
                    f"`{humanize_slug(stem)}`) so the declared name and the file's placement "
                    f"agree on which HA category this is. Until fixed, `hassle push` ignores "
                    f"`CATEGORY` for this file and falls back to a slug-derived name if it "
                    f"has to create the category."
                ),
            )
        )
    return findings


def validate_bundle(
    result: CompileResult,
    snapshot: RegistrySnapshot,
    adopted_helper_keys: frozenset[str] = frozenset(),
) -> list[Finding]:
    """Run every tier-2/3 check (DESIGN §9) against a compiled bundle. Offline; no network.

    ``adopted_helper_keys``: object keys (``"input_boolean:x"``) known to be
    adopted from a pull (typically the manifest's helper keys) -- the
    definitive exemption source for the helper-slug check, robust against
    post-creation entity renames that defeat entity-id inference.
    """
    findings: list[Finding] = []
    findings.extend(_validate_references(result, snapshot))
    findings.extend(_validate_purpose_vocabulary(result, snapshot))
    findings.extend(_validate_unknown_services(result, snapshot))
    findings.extend(_validate_service_params(result, snapshot))
    findings.extend(_validate_helper_slugs(result, snapshot, adopted_helper_keys))
    findings.extend(_validate_group_entities(result, snapshot))
    findings.extend(_validate_category_globals(result))
    return findings
