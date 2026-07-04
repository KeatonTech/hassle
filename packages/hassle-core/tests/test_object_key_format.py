"""M0 test 4 — object-key derivation for all object kinds (F1)."""

from __future__ import annotations

from hassle.ir import HELPER_DOMAINS, OBJECT_KINDS, object_key, parse


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
    # automation + script + 9 helper domains == 11 kinds
    assert len(OBJECT_KINDS) == 2 + len(HELPER_DOMAINS)
    assert len(HELPER_DOMAINS) == 9
