"""`hassle validate`'s blueprint rules — docs/internals/blueprints-design.md §6.

Offline, like every other tier-2 check. Three rules, each motivated by a **real
Home Assistant rejection** rather than by a schema guess — §6.4 makes that the
standing bar for adding a fourth:

1. **Instance inputs** (`blueprint-missing-input` / `blueprint-unknown-input`).
   An instance whose `use_blueprint` path matches a bundle-local blueprint is
   checked against that blueprint's declared `blueprint.input`. Exactly the
   class HA rejects with an opaque 400 at push time.
2. **Unmanaged blueprint** (`blueprint-not-in-bundle`, severity `warning`). An
   instance referencing a path with no bundle-local file. Legitimately common
   — a community blueprint imported into HA lives only there — so it is a
   warning, and the message names the file that would make it managed.
3. **The empty-optional-entity rule**
   (`blueprint-empty-optional-entity`), from the field 400 of 2026-08-10: an
   optional entity-selector input (`default: ""`) that appears as a literal
   `target.entity_id` / `entity_id` anywhere in the blueprint body. HA
   validates the **static** expanded config and rejects a literal empty id even
   inside a branch a runtime guard makes unreachable.

Rule 3's exemptions are as load-bearing as its trigger, and all three come from
the same real blueprint (BrandtCamp's `room-switch-controls.yaml`, the design's
worked example, which is clean):

- **`default: []` is exempt.** An empty *list* is the one way a state trigger
  can say "no entity" without failing to load — the opposite of the bug. §6.3
  names `default: ""` exactly.
- **A non-entity selector is exempt.** A `text:` input defaulting to `""` is a
  value, not an entity reference.
- **A required input is exempt.** With no `default:` it can never expand to an
  empty string, so a literal target is correct and idiomatic; flagging it would
  make every blueprint in existence noisy.
"""

from __future__ import annotations

import re
from typing import Any, cast

from hassle.blueprints import (
    BLUEPRINT_ROOT,
    blueprint_display_path,
    blueprint_key_for_use_path,
    input_ref_name,
    instance_inputs,
    parse_blueprint,
    split_blueprint_identity,
)
from hassle.compiler.bundle import CompileResult
from hassle.ir.keys import BLUEPRINT_KIND
from hassle.registry.didyoumean import did_you_mean
from hassle.registry.finding import Finding

_DESIGN_DOC = "docs/internals/blueprints-design.md"

#: Sentinel for "this input declared no `default:` at all", distinct from a
#: declared `default: null`.
_ABSENT: object = object()


def validate_blueprints(result: CompileResult) -> list[Finding]:
    """Every blueprint finding for one compiled bundle (§6)."""
    blueprints = {
        key: obj.to_ha() for key, obj in result.objects.items() if obj.kind() == BLUEPRINT_KIND
    }
    findings: list[Finding] = []
    findings.extend(_validate_instances(result, blueprints))
    findings.extend(_validate_empty_optional_entities(blueprints))
    return findings


# --- rules 1 and 2: the instances ------------------------------------------


def _validate_instances(
    result: CompileResult, blueprints: dict[str, dict[str, Any]]
) -> list[Finding]:
    findings: list[Finding] = []
    for key, obj in sorted(result.objects.items()):
        body = obj.to_ha()
        reference = body.get("use_blueprint")
        if not isinstance(reference, dict):
            continue
        path = cast("dict[str, Any]", reference).get("path")
        if not isinstance(path, str) or not path:
            continue
        span = result.decl_span_for(key)
        where_file = span.file if span is not None else None
        where_line = span.line if span is not None else None
        # An instance is always an AUTOMATION blueprint instance: that is what
        # `@blueprint_automation` declares (a `script` blueprint has no DSL
        # instance form in stage 1), so the key derives with no guessing.
        blueprint = blueprints.get(blueprint_key_for_use_path(path))
        if blueprint is None:
            findings.append(_not_in_bundle(key, path, where_file, where_line))
            continue
        findings.extend(
            _check_inputs(key, path, blueprint, instance_inputs(body), where_file, where_line)
        )
    return findings


def _not_in_bundle(object_key: str, path: str, file: str | None, line: int | None) -> Finding:
    display = blueprint_display_path(path)
    return Finding(
        code="blueprint-not-in-bundle",
        severity="warning",
        file=file,
        line=line,
        message=(
            f"`{object_key}` uses the blueprint `{path}`, which this bundle does not "
            f"contain -- so Hassle cannot push it, validate this automation's inputs "
            f"against it, or simulate the automation at all. That is fine if it is a "
            f"community blueprint you imported into Home Assistant by hand (it lives "
            f"only there, and Home Assistant cannot serve its source back)"
        ),
        fix=(
            f"save the blueprint's YAML into the bundle at `{display}` to bring it "
            f"under management -- Hassle will then push it before this automation, "
            f"check this automation's inputs offline, and expand it in tests. Leave it as it "
            f"is to keep referencing Home Assistant's own copy."
        ),
    )


def _check_inputs(
    object_key: str,
    path: str,
    blueprint: dict[str, Any],
    supplied: dict[str, Any],
    file: str | None,
    line: int | None,
) -> list[Finding]:
    declared = blueprint.get("inputs")
    if not isinstance(declared, dict):
        return []
    typed = cast("dict[str, Any]", declared)
    display = blueprint_display_path(path)
    findings: list[Finding] = []

    for name in sorted(_required(typed) - set(supplied)):
        findings.append(
            Finding(
                code="blueprint-missing-input",
                severity="error",
                file=file,
                line=line,
                message=(
                    f"`{object_key}` does not supply the blueprint input `{name}`, which "
                    f"`{display}` declares with no `default:` and therefore requires"
                ),
                fix=(
                    f'add `"{name}": ...` to this automation\'s `inputs=` dict, or give '
                    f"`{name}` a `default:` in the blueprint's `blueprint.input` block. "
                    f"Home Assistant rejects the automation the same way at save time, "
                    f"with an opaque HTTP 400."
                ),
            )
        )

    for name in sorted(set(supplied) - set(typed)):
        suggestion = did_you_mean(name, set(typed))
        hint = f" Did you mean `{suggestion}`?" if suggestion else ""
        findings.append(
            Finding(
                code="blueprint-unknown-input",
                severity="error",
                file=file,
                line=line,
                message=(
                    f"`{object_key}` supplies the blueprint input `{name}`, which "
                    f"`{display}` does not declare (it declares: "
                    f"{', '.join(f'`{n}`' for n in sorted(typed)) or 'none'})"
                ),
                fix=(
                    f"remove `{name}` from this automation's `inputs=` dict, or add it to "
                    f"the blueprint's `blueprint.input` block.{hint} Home Assistant "
                    f"rejects an unknown input the same way at save time."
                ),
            )
        )

    findings.extend(_check_entity_selectors(object_key, display, typed, supplied, file, line))
    return findings


#: An HA entity id is exactly ``<domain>.<object_id>``, both non-empty.
_ENTITY_ID = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")


def _check_entity_selectors(
    object_key: str,
    display: str,
    declared: dict[str, Any],
    supplied: dict[str, Any],
    file: str | None,
    line: int | None,
) -> list[Finding]:
    """An entity-selector input handed something that is not an entity id (§8.9).

    Stage 1 could not ask this question usefully of a hand-written blueprint and
    stage 2 does not change that -- a declared `selector: entity:` is equally
    readable in both -- but stage 2 is what made it worth asking: a DSL
    blueprint's `selector=` sits at the declaration site, so the mistake it
    catches ("kitchen" where a light entity was meant) is now a typo the author
    can be told about instead of another opaque HTTP 400 at push time.

    Deliberately narrow: only a plain string is judged, and only against the
    shape of an entity id. A list (entity selectors may accept several), a
    device/area id, or a templated value is left alone -- the rule exists to
    catch the obvious typo, not to re-implement HA's selector schema (§6.4's
    bar: each new rule motivated by a real rejection).
    """
    findings: list[Finding] = []
    for name in sorted(set(supplied) & set(declared)):
        spec = declared.get(name)
        if not isinstance(spec, dict) or "entity" not in cast("dict[str, Any]", spec).get(
            "selector", {}
        ):
            continue
        value = supplied[name]
        if not isinstance(value, str) or _ENTITY_ID.match(value) or "{" in value:
            continue
        findings.append(
            Finding(
                code="blueprint-input-not-an-entity-id",
                severity="error",
                file=file,
                line=line,
                message=(
                    f"`{object_key}` supplies `{value}` for the blueprint input `{name}`, "
                    f"which `{display}` declares as an entity selector, but that is not an "
                    f"entity id (Home Assistant entity ids are `<domain>.<object_id>`, "
                    f"e.g. `light.kitchen`)"
                ),
                fix=(
                    f'replace it with the full entity id, e.g. `"{name}": "light.{value}"` '
                    f"if that is the entity you meant. Home Assistant accepts the save and "
                    f"then silently never matches the entity, so this one does not even "
                    f"fail loudly at push time."
                ),
            )
        )
    return findings


def _required(declared: dict[str, Any]) -> set[str]:
    """Input names with no ``default:``.

    A bare `room_key:` entry parses as ``None``, not ``{}`` -- which is exactly
    why the IR keeps the block verbatim: "declared with no metadata at all" and
    "declared with an empty metadata mapping" are both required, and neither
    can be confused with "declared with a default".
    """
    required: set[str] = set()
    for name, spec in declared.items():
        if isinstance(spec, dict) and "default" in cast("dict[str, Any]", spec):
            continue
        required.add(str(name))
    return required


# --- rule 3: the empty-optional-entity rule --------------------------------


def _validate_empty_optional_entities(blueprints: dict[str, dict[str, Any]]) -> list[Finding]:
    findings: list[Finding] = []
    for key, body in sorted(blueprints.items()):
        source = body.get("source")
        declared = body.get("inputs")
        if not isinstance(source, str) or not isinstance(declared, dict):
            continue
        at_risk = _empty_optional_entity_inputs(cast("dict[str, Any]", declared))
        if not at_risk:
            continue
        identity = key.partition(":")[2]
        domain, path = split_blueprint_identity(identity)
        try:
            parsed = parse_blueprint(source, display_path=identity)
        except Exception:  # pragma: no cover - discovery already rejects these
            continue
        used = _inputs_used_as_literal_entity_id(parsed.body)
        for name in sorted(at_risk & used):
            findings.append(_empty_optional_finding(name, domain, path))
    return findings


def _empty_optional_entity_inputs(declared: dict[str, Any]) -> set[str]:
    """Inputs declared as an ENTITY selector with ``default: ""`` exactly.

    Both halves are deliberate (§6.3, and the module docstring's exemptions):
    ``default: []`` is the *correct* way to say "no entity" in a trigger, and a
    ``text:`` selector defaulting to ``""`` is a value, not an entity id.
    """
    at_risk: set[str] = set()
    for name, spec in declared.items():
        if not isinstance(spec, dict):
            continue
        typed = cast("dict[str, Any]", spec)
        # `default: ""` EXACTLY -- an identity check on the empty string, not
        # a falsiness test. `default: []` (the correct way for a trigger to say
        # "no entity") and `default: 0` are both falsy and both fine; only the
        # empty STRING is the shape HA rejects in an `entity_id` position.
        default = typed.get("default", _ABSENT)
        if not isinstance(default, str) or default != "":
            continue
        selector = typed.get("selector")
        if isinstance(selector, dict) and "entity" in cast("dict[str, Any]", selector):
            at_risk.add(str(name))
    return at_risk


def _inputs_used_as_literal_entity_id(node: Any) -> set[str]:
    """Input names appearing as a literal ``entity_id`` value anywhere.

    Covers `target: {entity_id: !input x}`, HA's legacy bare
    `entity_id: !input x` shorthand, and a list of ids containing one -- §6.3
    names `target.entity_id` / `entity_id`, and all three are the same position
    as far as HA's static validation is concerned.

    A templated value (`entity_id: "{{ x }}"`) is NOT a literal `!input` node
    and so never matches: that is precisely the fix this rule prescribes.
    """
    found: set[str] = set()
    _walk_for_entity_id(node, found)
    return found


def _walk_for_entity_id(node: Any, found: set[str]) -> None:
    if isinstance(node, dict):
        for key, value in cast("dict[Any, Any]", node).items():
            if key == "entity_id":
                _collect_input_refs(value, found)
            _walk_for_entity_id(value, found)
    elif isinstance(node, list):
        for item in cast("list[Any]", node):
            _walk_for_entity_id(item, found)


def _collect_input_refs(value: Any, found: set[str]) -> None:
    name = input_ref_name(value)
    if name is not None:
        found.add(name)
        return
    if isinstance(value, list):
        for item in cast("list[Any]", value):
            _collect_input_refs(item, found)


def _empty_optional_finding(name: str, domain: str, path: str) -> Finding:
    file = "/".join((BLUEPRINT_ROOT, domain, path))
    return Finding(
        code="blueprint-empty-optional-entity",
        severity="error",
        # The BLUEPRINT's bug, not any one instance's -- every instance would
        # hit it, so it is reported once, against the file. No line: the IR
        # carries the document as text, not as a span map (§1).
        file=file,
        line=None,
        message=(
            f"The blueprint input `{name}` is an optional entity selector defaulting to "
            f'`""`, and `{file}` uses it as a literal `entity_id:`. Home Assistant '
            f"validates the STATIC expanded configuration, so it rejects the empty "
            f"entity id with an opaque HTTP 400 at save time -- even when a runtime "
            f"condition means that branch could never execute with the input empty."
        ),
        fix=(
            f"bind the input to a run variable and use a TEMPLATED target instead of a "
            f"literal one: add `- variables: {{{name}: !input {name}}}` at the top of "
            f'`actions:`, then write `entity_id: "{{{{ {name} }}}}"`. A template defers '
            f"the check to runtime, where your existing guard means it never renders "
            f"empty. See {_DESIGN_DOC} §6.3 for the worked example."
        ),
    )
