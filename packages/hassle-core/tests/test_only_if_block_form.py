"""`only_if` block form.

`only_if(*conditions)` is dual-form: the bare call keeps its exact pre-existing
behavior (the frozen top-level DSL surface); used as `with only_if(...):` it
ALSO requires every action the automation records to be inside that one block
(an action recorded outside -- before or after -- raises
`OnlyIfBlockCoverageError`). The decompiler emits the block form whenever an
automation has any conditions at all; golden-pair parity proof lives in
fixtures/dsl/only_if_block_form/ vs. only_if_bare_form_parity/.
"""

from __future__ import annotations

import pytest

from hassle.compiler.bundle import compile_bundle
from hassle.compiler.errors import OnlyIfBlockCoverageError
from hassle.decompiler.codegen import decompile_bundle
from hassle.ir.canonical import sha256_hash
from hassle.ir.models import parse


def _write_bundle(tmp_path, source: str) -> str:
    (tmp_path / "objects.py").write_text(source, encoding="utf-8")
    return str(tmp_path)


def test_bare_only_if_unchanged_behavior(tmp_path) -> None:
    source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    only_if(state("input_boolean.x").is_("on"))\n'
        '    service("light.turn_on")\n'
        '    service("light.turn_off")\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    body = obj.to_ha()
    expected_condition = {"condition": "state", "entity_id": "input_boolean.x", "state": "on"}
    assert body["conditions"] == [expected_condition]
    assert len(body["actions"]) == 2


def test_block_form_records_conditions_and_all_actions(tmp_path) -> None:
    source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    with only_if(state("input_boolean.x").is_("on")):\n'
        '        service("light.turn_on")\n'
        '        service("light.turn_off")\n'
    )
    result = compile_bundle(_write_bundle(tmp_path, source))
    (obj,) = result.objects.values()
    body = obj.to_ha()
    expected_condition = {"condition": "state", "entity_id": "input_boolean.x", "state": "on"}
    assert body["conditions"] == [expected_condition]
    assert len(body["actions"]) == 2


def test_block_form_and_bare_form_compile_byte_identical(tmp_path) -> None:
    bare_source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    only_if(state("input_boolean.x").is_("on"))\n'
        '    service("light.turn_on")\n'
    )
    block_source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    with only_if(state("input_boolean.x").is_("on")):\n'
        '        service("light.turn_on")\n'
    )
    bare_dir = tmp_path / "bare"
    bare_dir.mkdir()
    block_dir = tmp_path / "block"
    block_dir.mkdir()
    bare_result = compile_bundle(_write_bundle(bare_dir, bare_source))
    block_result = compile_bundle(_write_bundle(block_dir, block_source))
    (bare_obj,) = bare_result.objects.values()
    (block_obj,) = block_result.objects.values()
    assert sha256_hash(bare_obj.to_ha()) == sha256_hash(block_obj.to_ha())


def test_action_after_block_closes_raises(tmp_path) -> None:
    source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    with only_if(state("input_boolean.x").is_("on")):\n'
        '        service("light.turn_on")\n'
        '    service("light.turn_off")\n'
    )
    with pytest.raises(OnlyIfBlockCoverageError):
        compile_bundle(_write_bundle(tmp_path, source))


def test_action_before_block_opens_raises(tmp_path) -> None:
    source = (
        "from hassle import automation, only_if, service, state\n\n\n"
        '@automation(id="a1", alias="A1")\n'
        "def a1():\n"
        '    service("light.turn_on")\n'
        '    with only_if(state("input_boolean.x").is_("on")):\n'
        '        service("light.turn_off")\n'
    )
    with pytest.raises(OnlyIfBlockCoverageError):
        compile_bundle(_write_bundle(tmp_path, source))


def test_error_message_is_what_where_fix() -> None:
    from hassle.compiler.spans import SourceSpan

    err = OnlyIfBlockCoverageError(SourceSpan(file="bad.py", line=13))
    message = str(err)
    assert "bad.py:13" in message
    assert "only_if" in message
    # fix guidance present
    assert "Fix:" in message


def test_no_conditions_no_block_in_decompiled_output() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [],
        "actions": [{"action": "light.turn_on"}],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "only_if" not in source
    assert "with only_if" not in source


def test_decompiler_emits_block_form_wrapping_all_actions_when_conditions_present() -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [],
        "conditions": [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}],
        "actions": [
            {"action": "light.turn_on"},
            {"action": "light.turn_off"},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "with only_if(" in source
    # A bare-call-form-only emission would be a regression -- there must be no
    # `only_if(...)` call OUTSIDE a `with` statement.
    assert "\n    only_if(" not in source or "with only_if(" in source


def test_decompiled_block_form_recompiles_byte_identical(tmp_path) -> None:
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "conditions": [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}],
        "actions": [
            {"action": "light.turn_on"},
            {"action": "light.turn_off"},
        ],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    bundle_dir = _write_bundle(tmp_path, source)
    result = compile_bundle(bundle_dir)
    (recompiled,) = result.objects.values()
    assert sha256_hash(recompiled.to_ha()) == sha256_hash(obj.to_ha())


def test_no_section_comments_emitted_anywhere() -> None:
    """Owner amendment (supersedes DESIGN §7.3's original latitude): section
    comments are removed entirely now that triggers/conditions/actions are
    each pinned to a self-describing location (decorator / only_if block /
    plain statements)."""
    config = {
        "id": "a1",
        "alias": "A1",
        "triggers": [{"trigger": "state", "entity_id": "binary_sensor.x", "to": "on"}],
        "conditions": [{"condition": "state", "entity_id": "input_boolean.x", "state": "on"}],
        "actions": [{"action": "light.turn_on"}],
    }
    obj = parse(config, kind="automation")
    source = decompile_bundle({obj.object_key(): obj})
    assert "# --- conditions ---" not in source
    assert "# --- actions ---" not in source
    assert "# --- triggers ---" not in source
    assert "# --- sequence ---" not in source
