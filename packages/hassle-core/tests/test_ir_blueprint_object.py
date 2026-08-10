"""The `blueprint` object kind and its IR body (blueprints-design §1).

Key: ``blueprint:<domain>/<path>`` — e.g.
``blueprint:automation/local/room-switch-controls.yaml``. ``<domain>`` is HA's
blueprint domain; ``<path>`` is *exactly* the string instances put in
``use_blueprint``, so the key can be derived from an instance's own reference
with no re-slugification (the same "identity is HA's own string, verbatim"
rule `dashboard` established for `url_path`).

The IR body is the raw YAML text, **byte-preserved** (the file is authored,
not generated, in stage 1), plus the parsed ``blueprint.input`` metadata the
validator (§6) reads. Anything else would make a push lose the author's
comments and formatting — and the whole document is what HA's
``blueprint/save`` takes.
"""

from __future__ import annotations

import pytest

from hassle.blueprints import blueprint_body
from hassle.ir import BLUEPRINT_KIND, OBJECT_KINDS, canonical_json, object_key, parse, serialize
from hassle.ir.models import BlueprintConfig
from hassle.ir.modernize import modernize_for_comparison
from hassle.ir.normalize import normalize_ha

SOURCE = """\
blueprint:
  name: Room Switch Controls
  domain: automation
  input:
    button_up:
      name: Up paddle
      selector:
        entity:
          filter:
            - domain: event
    # A bare input with no metadata at all is REQUIRED (HA allows this).
    room_key:
    lights_pause_boolean:
      name: Lights pause
      default: ""
      selector:
        entity:
          filter:
            - domain: input_boolean

triggers:
  - trigger: state
    entity_id: !input button_up
actions:
  - action: input_boolean.turn_on
    target:
      entity_id: "{{ lights_pause_boolean }}"
"""


def _body() -> dict[str, object]:
    return blueprint_body(
        domain="automation", path="local/room-switch-controls.yaml", source=SOURCE
    )


# --- the kind itself -------------------------------------------------------


def test_blueprint_is_an_object_kind() -> None:
    assert BLUEPRINT_KIND == "blueprint"
    assert BLUEPRINT_KIND in OBJECT_KINDS


def test_object_key_format() -> None:
    assert object_key(BLUEPRINT_KIND, "automation/local/x.yaml") == (
        "blueprint:automation/local/x.yaml"
    )


def test_identity_is_domain_slash_path_verbatim() -> None:
    obj = parse(_body(), kind=BLUEPRINT_KIND)
    assert obj.identity == "automation/local/room-switch-controls.yaml"
    assert obj.object_key() == "blueprint:automation/local/room-switch-controls.yaml"


def test_identity_never_reslugified() -> None:
    """`room-switch-controls.yaml` must NOT become `room_switch_controls_yaml`
    -- the path is the exact string instances put in `use_blueprint`, and a
    slugified key would address a file HA does not have."""
    obj = parse(
        blueprint_body(domain="automation", path="Cafe/Dim Lights.yaml", source=SOURCE),
        kind=BLUEPRINT_KIND,
    )
    assert obj.identity == "automation/Cafe/Dim Lights.yaml"


def test_key_opacity_split_on_first_colon_only() -> None:
    """ir-format.md's key-opacity rule, exercised: a blueprint identity holds
    slashes and dots. (It holds no colon today, but consumers must still split
    on the FIRST colon only.)"""
    key = parse(_body(), kind=BLUEPRINT_KIND).object_key()
    kind, _, identity = key.partition(":")
    assert kind == "blueprint"
    assert identity == "automation/local/room-switch-controls.yaml"


def test_parse_returns_a_blueprint_config() -> None:
    assert isinstance(parse(_body(), kind=BLUEPRINT_KIND), BlueprintConfig)


def test_kind_method() -> None:
    assert parse(_body(), kind=BLUEPRINT_KIND).kind() == "blueprint"


# --- the body --------------------------------------------------------------


def test_source_is_byte_preserved() -> None:
    obj = parse(_body(), kind=BLUEPRINT_KIND)
    assert obj.to_ha()["source"] == SOURCE


def test_source_preserves_comments_and_blank_lines() -> None:
    """Stage 1's file is AUTHORED, not generated: a push that dropped the
    author's comments would be a lossy round trip through Hassle."""
    source = obj_source = parse(_body(), kind=BLUEPRINT_KIND).to_ha()["source"]
    assert "# A bare input with no metadata at all is REQUIRED" in source
    assert "\n\ntriggers:" in obj_source


def test_source_preserves_crlf_verbatim() -> None:
    """Read as bytes, not through universal-newline text mode: HA stores what
    it is handed, so a CRLF file must not silently become LF on push."""
    crlf = SOURCE.replace("\n", "\r\n")
    body = blueprint_body(domain="automation", path="local/x.yaml", source=crlf)
    assert body["source"] == crlf


def test_inputs_metadata_is_parsed_verbatim() -> None:
    inputs = _body()["inputs"]
    assert isinstance(inputs, dict)
    assert set(inputs) == {"button_up", "room_key", "lights_pause_boolean"}
    # Verbatim -- the selector is what §6's rule 3 reads to tell an
    # entity-selector input from a text one.
    assert inputs["lights_pause_boolean"] == {
        "name": "Lights pause",
        "default": "",
        "selector": {"entity": {"filter": [{"domain": "input_boolean"}]}},
    }
    # A bare `room_key:` with no metadata parses as null, not as {} -- so
    # "declared with no default" (required) stays distinguishable.
    assert inputs["room_key"] is None


def test_domain_and_path_are_body_fields() -> None:
    body = _body()
    assert body["domain"] == "automation"
    assert body["path"] == "local/room-switch-controls.yaml"


# --- the frozen IR contracts ----------------------------------------------


def test_serialize_parse_round_trips() -> None:
    body = _body()
    assert serialize(parse(body, kind=BLUEPRINT_KIND)) == body


def test_unknown_fields_are_preserved() -> None:
    body = {**_body(), "future_field": {"nested": [1, 2]}}
    assert serialize(parse(body, kind=BLUEPRINT_KIND))["future_field"] == {"nested": [1, 2]}


def test_canonical_hash_is_stable_and_key_order_invariant() -> None:
    body = _body()
    reordered = dict(reversed(list(body.items())))
    assert canonical_json(body) == canonical_json(reordered)
    assert (
        parse(body, kind=BLUEPRINT_KIND).sha256() == parse(reordered, kind=BLUEPRINT_KIND).sha256()
    )


def test_hash_changes_when_the_yaml_changes() -> None:
    """A one-character edit to the authored file must plan an `update`."""
    a = parse(_body(), kind=BLUEPRINT_KIND).sha256()
    edited = blueprint_body(
        domain="automation",
        path="local/room-switch-controls.yaml",
        source=SOURCE.replace("Room Switch Controls", "Room Switch Controls v2"),
    )
    assert parse(edited, kind=BLUEPRINT_KIND).sha256() != a


@pytest.mark.parametrize("fn", [normalize_ha, modernize_for_comparison])
def test_normalization_is_identity_for_a_blueprint(fn: object) -> None:
    """A blueprint body is not an HA automation body: `source` is opaque text
    and `inputs` is selector metadata that legitimately contains keys like
    `service`/`delay`/`platform` inside a selector. Rewriting either would
    corrupt the authored file and drift the hash into a phantom conflict on
    every subsequent plan -- exactly the `dashboard` exemption's reasoning
    (ir-format.md)."""
    body = {
        **_body(),
        "inputs": {"knob": {"selector": {"select": {"options": ["service", "platform"]}}}},
    }
    assert fn(body, kind=BLUEPRINT_KIND) == body  # type: ignore[operator]


def test_normalization_returns_a_copy_not_the_input() -> None:
    body = _body()
    assert normalize_ha(body, kind=BLUEPRINT_KIND) is not body
