"""Object-key derivation for all object kinds, against the frozen IR schema.

``OBJECT_KINDS`` includes the four config-entry template-helper domains
(``TEMPLATE_DOMAINS``, docs/internals/ha-api-notes.md §26) and the twelve config-entry
group-helper domains (``GROUP_DOMAINS``, docs/internals/ha-api-notes.md §38). The key
*format* (``"<kind>:<identity>"``) stays fixed; only the enumerated domain
vocabulary grows, exactly as it would for any future helper domain.
"""

from __future__ import annotations

from hassle.ir import HELPER_DOMAINS, OBJECT_KINDS, object_key, parse
from hassle.ir.keys import GROUP_DOMAINS, TEMPLATE_DOMAINS


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
    assert GROUP_DOMAINS <= OBJECT_KINDS
    assert "dashboard" in OBJECT_KINDS
    # automation + script + dashboard + 9 storage helper domains +
    # 4 template domains + 12 group domains == 28 kinds
    assert len(OBJECT_KINDS) == 3 + len(HELPER_DOMAINS) + len(TEMPLATE_DOMAINS) + len(GROUP_DOMAINS)
    assert len(HELPER_DOMAINS) == 9
    assert len(TEMPLATE_DOMAINS) == 4
    assert len(GROUP_DOMAINS) == 12


def test_object_key_for_every_template_domain() -> None:
    # Identity redesign (docs/internals/ha-api-notes.md §26.6): there is no `unique_id`
    # -- the flow's real form schema rejects it as an unrecognized key.
    # Identity is derived from `name` (slugified), mirroring the storage
    # helpers' "id is a slug of name" rule.
    for domain in TEMPLATE_DOMAINS:
        obj = parse({"name": "Some Thing"}, kind=domain)
        assert obj.object_key() == f"{domain}:some_thing"


def test_object_key_for_template_domain_uses_key_hint_when_supplied() -> None:
    # A key_hint (read-back path: DirectBackend/FakeBackend re-derive the
    # identity from the entry's title and pass it as key_hint, mirroring
    # how a script's extrinsic object_id is supplied) takes priority over
    # re-deriving from `name`.
    obj = parse({"name": "Some Thing"}, kind="template_number", key_hint="some_thing")
    assert obj.object_key() == "template_number:some_thing"


def test_object_key_for_every_group_domain() -> None:
    # Same identity rule as template (docs/internals/ha-api-notes.md §38.1): no
    # `unique_id` -- identity is derived from `name` (slugified).
    for domain in GROUP_DOMAINS:
        obj = parse({"name": "Some Thing"}, kind=domain)
        assert obj.object_key() == f"{domain}:some_thing"


def test_object_key_for_group_domain_uses_key_hint_when_supplied() -> None:
    obj = parse({"name": "Some Thing"}, kind="group_cover", key_hint="some_thing")
    assert obj.object_key() == "group_cover:some_thing"
