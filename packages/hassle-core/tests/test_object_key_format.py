"""M0 test 4 — object-key derivation for all object kinds (F1).

M10 note: ``OBJECT_KINDS`` widened additively to include the four config-entry
template-helper domains (``TEMPLATE_DOMAINS``, docs/ha-api-notes.md §26) — the
key *format* (``"<kind>:<identity>"``) is unchanged; only the enumerated domain
vocabulary grew, exactly as it would for any future helper domain. The count
assertion below is updated in the same PR (R5).
"""

from __future__ import annotations

from hassle.ir import HELPER_DOMAINS, OBJECT_KINDS, object_key, parse
from hassle.ir.keys import TEMPLATE_DOMAINS


def test_object_key_string_format() -> None:
    assert object_key("automation", "hall_light_on_motion") == "automation:hall_light_on_motion"
    assert object_key("input_boolean", "guest_mode") == "input_boolean:guest_mode"
    assert object_key("script", "movie_time") == "script:movie_time"


def test_object_key_from_automation_uses_body_id() -> None:
    obj = parse({"id": "hall_light_on_motion", "trigger": [], "action": []}, kind="automation")
    assert obj.object_key() == "automation:hall_light_on_motion"


def test_object_key_from_script_uses_object_id_hint() -> None:
    obj = parse({"alias": "Movie time", "sequence": []}, kind="script", key_hint="movie_time")
    assert obj.object_key() == "script:movie_time"


def test_object_key_for_every_helper_domain() -> None:
    for domain in HELPER_DOMAINS:
        obj = parse({"id": f"{domain}_thing", "name": "X"}, kind=domain)
        assert obj.object_key() == f"{domain}:{domain}_thing"


def test_object_kinds_cover_automation_script_and_helpers() -> None:
    assert "automation" in OBJECT_KINDS
    assert "script" in OBJECT_KINDS
    assert HELPER_DOMAINS <= OBJECT_KINDS
    assert TEMPLATE_DOMAINS <= OBJECT_KINDS
    # automation + script + 9 storage helper domains + 4 template domains == 15 kinds
    assert len(OBJECT_KINDS) == 2 + len(HELPER_DOMAINS) + len(TEMPLATE_DOMAINS)
    assert len(HELPER_DOMAINS) == 9
    assert len(TEMPLATE_DOMAINS) == 4


def test_object_key_for_every_template_domain() -> None:
    for domain in TEMPLATE_DOMAINS:
        obj = parse({"unique_id": f"{domain}_thing", "name": "X"}, kind=domain)
        assert obj.object_key() == f"{domain}:{domain}_thing"
