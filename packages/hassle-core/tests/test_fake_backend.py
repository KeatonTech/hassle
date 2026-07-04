"""FakeBackend — in-memory Backend for M5 (docs/ha-api-notes.md §11).

Seeded from shapes in docs/ha-api-captures/ (hand-written Python fixture data
modeled on those captures, not parsed at runtime — see module docstring in
hassle/backend/fake.py for provenance comments per capture).

Key behaviors under test:
- normalizes create/update input through `hassle.ir.normalize_ha` before storing
  (legacy singular -> plural, `service:` -> `action:`), exactly like real HA;
- helper create/update/delete addressed by domain + id (the `{domain}_id`
  convention, docs/ha-api-notes.md §4);
- tracks writes since last reset so tests can assert zero writes during pull.
"""

from __future__ import annotations

import pytest

from hassle.backend.fake import FakeBackend


def test_fake_backend_seeded_with_automation_and_script() -> None:
    backend = FakeBackend.with_seed_data()
    automations = backend.list_remote("automation")
    scripts = backend.list_remote("script")
    assert len(automations) >= 1
    assert len(scripts) >= 1


def test_fake_backend_seeded_with_all_helper_domains() -> None:
    backend = FakeBackend.with_seed_data()
    for domain in (
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    ):
        assert isinstance(backend.list_remote(domain), dict)


def test_fake_backend_list_remote_returns_plural_form() -> None:
    backend = FakeBackend()
    backend.create(
        "automation",
        {
            "id": "a1",
            "alias": "Test",
            "trigger": [{"platform": "state", "entity_id": "a"}],
            "condition": [],
            "action": [{"service": "light.turn_on"}],
        },
    )
    stored = backend.list_remote("automation")["a1"]
    assert "triggers" in stored and "trigger" not in stored
    assert stored["actions"][0]["action"] == "light.turn_on"


def test_fake_backend_create_normalizes_legacy_singular_input() -> None:
    backend = FakeBackend()
    identity = backend.create(
        "script",
        {
            "alias": "Test Script",
            "sequence": [{"service": "input_boolean.toggle"}],
        },
    )
    stored = backend.list_remote("script")[identity]
    assert stored["sequence"][0]["action"] == "input_boolean.toggle"
    assert "service" not in stored["sequence"][0]


def test_fake_backend_update_normalizes_input() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "A"})
    backend.update(
        "automation",
        identity,
        {"id": "a1", "alias": "A2", "action": [{"service": "light.turn_off"}]},
    )
    stored = backend.list_remote("automation")[identity]
    assert stored["actions"][0]["action"] == "light.turn_off"


def test_fake_backend_delete_removes_object() -> None:
    backend = FakeBackend()
    identity = backend.create("automation", {"id": "a1", "alias": "A"})
    backend.delete("automation", identity)
    assert identity not in backend.list_remote("automation")


def test_fake_backend_helper_create_update_delete_cycle() -> None:
    backend = FakeBackend()
    identity = backend.create("input_boolean", {"name": "Guest Mode"})
    assert identity in backend.list_remote("input_boolean")
    backend.update("input_boolean", identity, {"name": "Guest Mode 2"})
    assert backend.list_remote("input_boolean")[identity]["name"] == "Guest Mode 2"
    backend.delete("input_boolean", identity)
    assert identity not in backend.list_remote("input_boolean")


@pytest.mark.parametrize(
    "domain",
    [
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    ],
)
def test_fake_backend_all_helper_domains_support_full_cycle(domain: str) -> None:
    backend = FakeBackend()
    identity = backend.create(domain, {"name": f"Test {domain}"})
    assert backend.list_remote(domain)[identity]["name"] == f"Test {domain}"
    backend.update(domain, identity, {"name": "Updated"})
    assert backend.list_remote(domain)[identity]["name"] == "Updated"
    backend.delete(domain, identity)
    assert identity not in backend.list_remote(domain)


def test_fake_backend_tracks_writes_since_reset() -> None:
    backend = FakeBackend()
    assert backend.writes_since_reset() == 0
    backend.create("automation", {"id": "a1", "alias": "A"})
    assert backend.writes_since_reset() == 1
    backend.update("automation", "a1", {"id": "a1", "alias": "A2"})
    assert backend.writes_since_reset() == 2
    backend.delete("automation", "a1")
    assert backend.writes_since_reset() == 3


def test_fake_backend_reset_write_tracking_clears_counter() -> None:
    backend = FakeBackend()
    backend.create("automation", {"id": "a1", "alias": "A"})
    backend.reset_write_tracking()
    assert backend.writes_since_reset() == 0


def test_fake_backend_list_remote_does_not_count_as_write() -> None:
    backend = FakeBackend.with_seed_data()
    backend.reset_write_tracking()
    backend.list_remote("automation")
    backend.list_remote("script")
    assert backend.writes_since_reset() == 0
