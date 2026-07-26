"""Remote HA config must never become executable code in a decompiled bundle.

Decompilation turns config fetched from Home Assistant into Python source that
the user's machine then imports -- during `hassle pull`'s own self-check,
before anything is written to disk. So any place where remote data reaches the
generated source as *code* rather than as a *literal* is a remote-code-
execution path.

Two shapes are covered here:

- **values** rendered into literals (`render_literal`/`repr`), and
- **keys** used as keyword-argument names, which cannot be escaped as
  identifiers at all -- an unsafe name is routed through `**{...}` so it stays
  a literal.

The IR keeps unknown fields (``extra="allow"``) so `compile(decompile(x)) == x`
holds for any config, which is exactly why a hostile field name can reach
codegen in the first place.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import Any

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.models import parse

# Payloads that try to break out of a literal or an identifier position.
HOSTILE = [
    'x" + __import__("os").system("touch /tmp/pwned") + "',
    "x' + __import__('os').system('touch /tmp/pwned') + '",
    'x"""\nimport os\n"""',
    'x\\" + str(1) + \\"',
    "x\n#",
    "x) or __import__('os').system('id') or (",
]

# Field *names* an attacker could store in HA that are not safe identifiers.
HOSTILE_KEYS = [
    'evil=__import__("os").system("id") #',
    "weird key",
    "class",  # a valid identifier, but a Python keyword
    "def",
    "1leading_digit",
    "kebab-case",
    "",
]


def _assert_no_execution(source: str) -> ast.Module:
    """The generated source must parse, and contain no call machinery that
    could only have come from injected text."""
    tree = ast.parse(source)  # SyntaxError here is itself a bug
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in {"__import__", "eval", "exec", "compile"}:
            raise AssertionError(f"injected executable name {node.id!r} in generated source")
        if isinstance(node, ast.Attribute) and node.attr in {"system", "popen", "__globals__"}:
            raise AssertionError(f"injected executable attribute {node.attr!r} in generated source")
    return tree


def _roundtrip(tmp_path: Path, key: str, config: dict[str, Any], kind: str) -> dict[str, Any]:
    """Decompile one object, assert the source is inert, recompile it, and
    return the recompiled config so the caller can pin the round-trip."""
    obj = parse(config, kind=kind, key_hint=config.get("id", "x"))
    source = decompile_bundle({key: obj})
    _assert_no_execution(source)
    bundle = tmp_path / "bundle"
    bundle.mkdir(exist_ok=True)
    (bundle / "objects.py").write_text(source, encoding="utf-8")
    result = compile_bundle(bundle)
    assert key in result.objects, f"recompiled bundle lost {key}: {list(result.objects)}"
    return dict(result.objects[key].to_ha())


@pytest.mark.parametrize("payload", HOSTILE)
def test_blueprint_path_cannot_inject_code(tmp_path: Path, payload: str) -> None:
    """`use_blueprint.path` is free text an HA user or integration controls."""
    config = {"id": "bp", "use_blueprint": {"path": payload, "input": {}}}
    recompiled = _roundtrip(tmp_path, "automation:bp", config, "automation")
    assert recompiled["use_blueprint"]["path"] == payload


@pytest.mark.parametrize("payload", HOSTILE)
def test_blueprint_input_values_cannot_inject_code(tmp_path: Path, payload: str) -> None:
    config = {"id": "bp", "use_blueprint": {"path": "ok.yaml", "input": {"light": payload}}}
    recompiled = _roundtrip(tmp_path, "automation:bp", config, "automation")
    assert recompiled["use_blueprint"]["input"]["light"] == payload


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_helper_field_names_cannot_inject_code(tmp_path: Path, key: str) -> None:
    """Storage-collection helpers render every stored field as a kwarg."""
    config = {"id": "h", "name": "n", key: "v"}
    recompiled = _roundtrip(tmp_path, "input_boolean:h", config, "input_boolean")
    assert recompiled[key] == "v"


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_script_field_names_cannot_inject_code(key: str) -> None:
    """Scripts only assert inertness, not the round trip.

    `@script`/`@shared_script` reject options outside HA's known set, so a
    script carrying an unknown top-level key does not survive
    decompile -> compile at all (tracked by
    :func:`test_script_unknown_top_level_key_roundtrip_is_a_known_gap`).
    That is a fidelity gap, not a security one: what matters here is that the
    generated source is inert.
    """
    obj = parse({"id": "s", "alias": "S", "sequence": [], key: "v"}, kind="script", key_hint="s")
    _assert_no_execution(decompile_bundle({"script:s": obj}))


@pytest.mark.xfail(
    strict=True,
    reason=(
        "known gap: the script decorators accept only HA's documented options, "
        "and there is no raw_script escape hatch, so an unknown stored field "
        "cannot round-trip. Pre-existing; before the injection fix this produced "
        "a SyntaxError instead."
    ),
)
def test_script_unknown_top_level_key_roundtrip_is_a_known_gap(tmp_path: Path) -> None:
    recompiled = _roundtrip(
        tmp_path, "script:s", {"id": "s", "alias": "S", "sequence": [], "surprise": "v"}, "script"
    )
    assert recompiled["surprise"] == "v"


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_template_helper_field_names_cannot_inject_code(tmp_path: Path, key: str) -> None:
    config = {
        "id": "t",
        "name": "T",
        "state": "{{ 1 }}",
        "unique_id": "t",
        key: "v",
    }
    recompiled = _roundtrip(tmp_path, "template_sensor:t", config, "template_sensor")
    assert recompiled[key] == "v"


@pytest.mark.parametrize("payload", HOSTILE)
def test_helper_values_cannot_inject_code(tmp_path: Path, payload: str) -> None:
    config = {"id": "h", "name": payload}
    recompiled = _roundtrip(tmp_path, "input_boolean:h", config, "input_boolean")
    assert recompiled["name"] == payload


@pytest.mark.parametrize("payload", HOSTILE)
def test_automation_alias_and_description_cannot_inject_code(tmp_path: Path, payload: str) -> None:
    config = {
        "id": "a",
        "alias": payload,
        "description": payload,
        "triggers": [],
        "conditions": [],
        "actions": [],
    }
    recompiled = _roundtrip(tmp_path, "automation:a", config, "automation")
    assert recompiled["alias"] == payload
    assert recompiled["description"] == payload


@pytest.mark.parametrize("key", HOSTILE_KEYS)
def test_service_data_field_names_cannot_inject_code(tmp_path: Path, key: str) -> None:
    """HA service-data field names are unconstrained strings, and the typed
    namespace form writes them as Python kwargs."""
    config = {
        "id": "a",
        "triggers": [],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "data": {key: "v"}}],
    }
    recompiled = _roundtrip(tmp_path, "automation:a", config, "automation")
    assert recompiled["actions"][0]["data"][key] == "v"


@pytest.mark.parametrize("payload", HOSTILE)
def test_service_action_and_data_values_cannot_inject_code(tmp_path: Path, payload: str) -> None:
    config = {
        "id": "a",
        "triggers": [],
        "conditions": [],
        "actions": [{"action": "light.turn_on", "data": {"message": payload}}],
    }
    recompiled = _roundtrip(tmp_path, "automation:a", config, "automation")
    assert recompiled["actions"][0]["data"]["message"] == payload
