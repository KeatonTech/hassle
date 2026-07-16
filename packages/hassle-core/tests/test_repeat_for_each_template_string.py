"""The `for_each` template-string bug.

HA's `repeat.for_each` may be stored as a Jinja template STRING that renders to a list at
runtime, not just a literal list. `repeat_for_each()`'s `list(items)` call silently exploded a
string into a list of individual characters (a `str` IS an `Iterable[str]`) instead of passing
it through verbatim -- this module pins the fix on both the compiler and decompiler sides.
"""

from __future__ import annotations

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import parse


def _write_bundle(tmp_path, source: str) -> str:
    (tmp_path / "objects.py").write_text(source, encoding="utf-8")
    return str(tmp_path)


def test_repeat_for_each_string_passes_through_verbatim_not_exploded(tmp_path) -> None:
    """The regression itself: `repeat_for_each("{{ ... }}")` must record the
    template string verbatim, never `list("{{ ... }}")`'s character explosion."""
    source = (
        "from hassle import automation, repeat_for_each, service, state, when\n\n\n"
        '@automation(id="a1", alias="A1", triggers=[state("input_text.x").to("on")])\n'
        "def a1():\n"
        "    with repeat_for_each(\"{{ states.light | map(attribute='entity_id') | list }}\"):\n"
        '        service("light.turn_on", target={"entity_id": "{{ repeat.item }}"})\n'
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (obj,) = result.objects.values()
    body = obj.to_ha()
    for_each = body["actions"][0]["repeat"]["for_each"]
    assert for_each == "{{ states.light | map(attribute='entity_id') | list }}"
    # The historical bug: this would have been a 60+ element list of single characters.
    assert isinstance(for_each, str)


def test_repeat_for_each_list_still_materializes_a_list(tmp_path) -> None:
    """Non-string iterables must still become a real list (unchanged behavior) --
    only a bare string gets the pass-through treatment."""
    source = (
        "from hassle import automation, repeat_for_each, service, state, when\n\n\n"
        '@automation(id="a1", alias="A1", triggers=[state("input_text.x").to("on")])\n'
        "def a1():\n"
        '    with repeat_for_each(["light.bedroom", "light.kitchen"]):\n'
        '        service("light.turn_on", target={"entity_id": "{{ repeat.item }}"})\n'
    )
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (obj,) = result.objects.values()
    for_each = obj.to_ha()["actions"][0]["repeat"]["for_each"]
    assert for_each == ["light.bedroom", "light.kitchen"]


def test_decompiler_emits_repeat_for_each_string_call() -> None:
    """Decompiler side: a stored template-string `for_each` must decompile to
    `repeat_for_each("{{ ... }}")`, not an exploded character list literal."""
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [
            {
                "repeat": {
                    "for_each": "{{ states.light | map(attribute='entity_id') | list }}",
                    "sequence": [
                        {
                            "action": "light.turn_on",
                            "target": {"entity_id": "{{ repeat.item }}"},
                        }
                    ],
                }
            }
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "repeat_for_each(\"{{ states.light | map(attribute='entity_id') | list }}\"):" in source
    # Never a giant character-list literal.
    assert "repeat_for_each(['{'" not in source


def test_repeat_for_each_string_roundtrips_byte_identical(tmp_path) -> None:
    """Full round-trip (compile(decompile(x)) == x): decompile -> recompile
    of a template-string `for_each` must be canonical-hash-identical to the
    original -- the exact invariant that silently failed before this fix."""
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [{"trigger": "state", "entity_id": "input_text.entities", "to": "on"}],
        "conditions": [],
        "actions": [
            {
                "repeat": {
                    "for_each": "{{ states.light | map(attribute='entity_id') | list }}",
                    "sequence": [
                        {
                            "action": "light.turn_on",
                            "target": {"entity_id": "{{ repeat.item }}"},
                        }
                    ],
                }
            }
        ],
        "mode": "single",
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())
