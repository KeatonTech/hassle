"""`DashboardConfig` — the two-store envelope (docs/internals/dashboards-design.md §3.2).

A dashboard is two HA-side objects (a `lovelace_dashboards` registry item and a
`lovelace[.<url_path>]` config blob) but ONE Hassle object, so the IR body is a
Hassle-composed envelope:

    {"meta": <registry item minus id/mode> | null, "config": <view config verbatim>}

Both halves are native-JSON passthrough (`Any`), exactly like `triggers`/
`actions` on `AutomationConfig`, so the frozen `serialize(parse(x)) == x`
contract (ir-format.md, I3) holds by construction.
"""

from __future__ import annotations

import copy
import json
from typing import Any

from _dashboard_fixtures import DASHBOARD_ENVELOPE, DEFAULT_DASHBOARD_ENVELOPE

from hassle.ir import (
    OBJECT_KINDS,
    canonical_json,
    object_key,
    parse,
    serialize,
    sha256_hash,
)
from hassle.ir.keys import DASHBOARD_KIND
from hassle.ir.models import DashboardConfig

# -- kind registration -----------------------------------------------------


def test_dashboard_kind_constant_and_membership() -> None:
    assert DASHBOARD_KIND == "dashboard"
    assert DASHBOARD_KIND in OBJECT_KINDS


def test_object_key_for_dashboard() -> None:
    assert object_key("dashboard", "climate-control") == "dashboard:climate-control"
    # The default dashboard's sentinel identity. Safe by construction: a real
    # `url_path` must contain a hyphen (§2.2 item 1), so `default` can never
    # collide with one.
    assert object_key("dashboard", "default") == "dashboard:default"


# -- parse/serialize round-trip (I3) ---------------------------------------


def test_dashboard_envelope_roundtrips_verbatim() -> None:
    obj = parse(DASHBOARD_ENVELOPE, kind="dashboard")
    assert isinstance(obj, DashboardConfig)
    assert obj.kind() == "dashboard"
    assert serialize(obj) == DASHBOARD_ENVELOPE


def test_default_dashboard_envelope_roundtrips_with_null_meta() -> None:
    """`meta: null` is a SET field, not an absent one: `exclude_unset=True`
    must still emit it, or the default dashboard's envelope would silently
    lose the very key that marks it as the default."""
    obj = parse(DEFAULT_DASHBOARD_ENVELOPE, kind="dashboard")
    out = serialize(obj)
    assert out == DEFAULT_DASHBOARD_ENVELOPE
    assert "meta" in out
    assert out["meta"] is None


def test_dashboard_roundtrip_is_byte_exact_not_merely_equal() -> None:
    """Key order is not semantically meaningful, but no key may be added,
    dropped, or reordered *within a list* — assert on canonical JSON so a
    silently materialized default would fail loudly."""
    obj = parse(DASHBOARD_ENVELOPE, kind="dashboard")
    assert canonical_json(serialize(obj)) == canonical_json(DASHBOARD_ENVELOPE)


def test_dashboard_parse_does_not_mutate_input() -> None:
    before = json.dumps(DASHBOARD_ENVELOPE, sort_keys=True)
    parse(DASHBOARD_ENVELOPE, kind="dashboard")
    assert json.dumps(DASHBOARD_ENVELOPE, sort_keys=True) == before


# -- unknown-field preservation (I3) ---------------------------------------


def test_dashboard_preserves_unknown_fields_at_envelope_top_level() -> None:
    out = serialize(parse(DASHBOARD_ENVELOPE, kind="dashboard"))
    assert out["invented_envelope_key"] == {"top": "level"}


def test_dashboard_preserves_unknown_fields_deep_inside_cards() -> None:
    out = serialize(parse(DASHBOARD_ENVELOPE, kind="dashboard"))
    view = out["config"]["views"][0]
    section = view["sections"][0]
    tile = section["cards"][1]
    stack = section["cards"][2]
    custom = stack["cards"][1]["card"]

    assert out["meta"]["invented_meta_key"] == {"kept": [1, 2, 3]}
    assert out["config"]["invented_config_key"] == "kept"
    assert view["invented_view_key"] == {"deep": {"deeper": "kept"}}
    assert section["invented_section_key"] == ["kept", {"still": "here"}]
    assert tile["invented_card_key"] == {"deepest": 3.14}
    assert custom["unknown_custom_key"] == {"a": [None, True, "z"]}
    # A third-party card type is preserved verbatim — never normalized,
    # never guessed at (D-G5).
    assert custom["type"] == "custom:bubble-card"


def test_dashboard_preserves_legacy_masonry_view_without_type_key() -> None:
    """An absent `type` key is the legacy-masonry storage shape (§2.2 item 4).
    Parsing must not materialize a default into it."""
    out = serialize(parse(DASHBOARD_ENVELOPE, kind="dashboard"))
    legacy_view = out["config"]["views"][1]
    assert "type" not in legacy_view


# -- identity derivation (§3.1/§3.2) ---------------------------------------


def test_identity_comes_from_meta_url_path() -> None:
    obj = parse(DASHBOARD_ENVELOPE, kind="dashboard")
    assert obj.identity == "climate-control"
    assert obj.object_key() == "dashboard:climate-control"


def test_meta_url_path_wins_over_key_hint() -> None:
    """The envelope is self-describing: identity always travels inside it, so
    a stale key_hint can never override it."""
    obj = parse(DASHBOARD_ENVELOPE, kind="dashboard", key_hint="something-else")
    assert obj.identity == "climate-control"


def test_identity_falls_back_to_key_hint_when_meta_is_null() -> None:
    obj = parse(DEFAULT_DASHBOARD_ENVELOPE, kind="dashboard", key_hint="default")
    assert obj.identity == "default"
    assert obj.object_key() == "dashboard:default"


def test_identity_falls_back_to_default_sentinel_with_no_meta_and_no_hint() -> None:
    obj = parse(DEFAULT_DASHBOARD_ENVELOPE, kind="dashboard")
    assert obj.identity == "default"
    assert obj.object_key() == "dashboard:default"


def test_identity_falls_back_to_default_for_meta_without_url_path() -> None:
    """A registry item that somehow carries no `url_path` must still key
    deterministically rather than raising — `_key_id` first, then the
    sentinel."""
    envelope: dict[str, Any] = {"meta": {"title": "Odd"}, "config": {"views": []}}
    assert parse(envelope, kind="dashboard").identity == "default"
    assert parse(envelope, kind="dashboard", key_hint="odd-one").identity == "odd-one"


def test_identity_ignores_a_non_dict_meta() -> None:
    """`meta` is passthrough `Any`; a malformed body must round-trip rather
    than crash identity derivation (I3 outranks tidiness)."""
    envelope: dict[str, Any] = {"meta": "not-a-dict", "config": {}}
    obj = parse(envelope, kind="dashboard")
    assert obj.identity == "default"
    assert serialize(obj) == envelope


def test_identity_for_a_non_string_url_path_is_stringified() -> None:
    envelope: dict[str, Any] = {"meta": {"url_path": 7}, "config": {}}
    obj = parse(envelope, kind="dashboard")
    assert obj.identity == "7"
    assert serialize(obj) == envelope


# -- canonical hashing (R8 — determinism) ----------------------------------


def _reverse_key_order(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _reverse_key_order(v) for k, v in reversed(list(obj.items()))}
    if isinstance(obj, list):
        return [_reverse_key_order(v) for v in obj]
    return obj


def test_dashboard_hash_is_key_order_invariant() -> None:
    shuffled = _reverse_key_order(DASHBOARD_ENVELOPE)
    assert json.dumps(shuffled) != json.dumps(DASHBOARD_ENVELOPE)
    assert sha256_hash(shuffled) == sha256_hash(DASHBOARD_ENVELOPE)


def test_dashboard_hash_is_byte_stable_across_parses() -> None:
    first = parse(DASHBOARD_ENVELOPE, kind="dashboard").sha256()
    second = parse(copy.deepcopy(DASHBOARD_ENVELOPE), kind="dashboard").sha256()
    assert first == second
    assert first == sha256_hash(DASHBOARD_ENVELOPE)
    assert first.startswith("sha256:")
    assert len(first) == len("sha256:") + 64


def test_dashboard_hash_is_card_order_sensitive() -> None:
    """List order is semantically meaningful EVERYWHERE in a dashboard —
    views, sections, cards — and canonical JSON preserves it (§3.3)."""
    reordered = copy.deepcopy(DASHBOARD_ENVELOPE)
    reordered["config"]["views"].reverse()
    assert sha256_hash(reordered) != sha256_hash(DASHBOARD_ENVELOPE)

    swapped_cards = copy.deepcopy(DASHBOARD_ENVELOPE)
    cards = swapped_cards["config"]["views"][0]["sections"][0]["cards"]
    cards[0], cards[1] = cards[1], cards[0]
    assert sha256_hash(swapped_cards) != sha256_hash(DASHBOARD_ENVELOPE)


def test_dashboard_hash_covers_both_halves_of_the_envelope() -> None:
    """A UI edit to EITHER the sidebar metadata or the cards shows up as one
    drifted object (§3.2) — the hash must move for both."""
    base = parse(DASHBOARD_ENVELOPE, kind="dashboard").sha256()

    meta_edit = copy.deepcopy(DASHBOARD_ENVELOPE)
    meta_edit["meta"]["title"] = "Climate Control"
    assert parse(meta_edit, kind="dashboard").sha256() != base

    config_edit = copy.deepcopy(DASHBOARD_ENVELOPE)
    config_edit["config"]["views"][0]["title"] = "Renamed"
    assert parse(config_edit, kind="dashboard").sha256() != base
