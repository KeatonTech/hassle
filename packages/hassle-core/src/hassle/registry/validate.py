"""The M3 validator (DESIGN §9 tiers 1-3): `validate_bundle(compile_result,
snapshot) -> list[Finding]`.

Offline only (fixtures/registry snapshot); no network. Covers:
- unknown entity/area/floor/label/device references (milestone test 1, 2b),
  including references nested inside if/choose/repeat/parallel/
  wait_for_trigger action containers (see `hassle.registry.extract`'s
  recursive descent)
- did-you-mean suggestions (test 2)
- purpose-vocabulary validation + known-renames hints (test 2b)
- bundle-declared helpers counting as existing (test 3)
- service-call parameter validation: unknown/wrong-type/missing-required (test 4)

## Coverage boundaries (deliberate permissiveness; M9's docs generator
sources this section for the agent-facing docs, so keep it accurate)

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

from typing import Any, cast

from hassle.compiler.bundle import CompileResult
from hassle.compiler.spans import SourceSpan
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


def _bundle_declared_keys(result: CompileResult) -> set[str]:
    """``"<domain>:<id>"`` keys for every object this bundle itself declares:
    helper domains (milestone test 3) plus automations/scripts (an automation
    referencing its own or a sibling automation/script entity, e.g.
    ``automation.turn_off`` targeting itself, or a ``script.<id>`` call,
    counts as existing exactly like a bundle-declared helper).
    """
    return set(result.objects)


def _check_entity(
    entity_id: str,
    *,
    snapshot: RegistrySnapshot,
    declared_helpers: set[str],
    file: str | None,
    line: int | None,
) -> Finding | None:
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


def validate_bundle(result: CompileResult, snapshot: RegistrySnapshot) -> list[Finding]:
    """Run every M3 tier-2/3 check against a compiled bundle. Offline; no network."""
    findings: list[Finding] = []
    findings.extend(_validate_references(result, snapshot))
    findings.extend(_validate_purpose_vocabulary(result, snapshot))
    findings.extend(_validate_service_params(result, snapshot))
    return findings
