"""Dashboard CRUD against real HA (docs/internals/dashboards-design.md
§4.1/§9.2).

**Source-informed, DB0-pending**: everything this suite asserts about the
wire shapes (`lovelace/dashboards/*`, `lovelace/config*`) is the §2
hypothesis, not yet captured/verified against a live instance
(docs/internals/dashboards-design.md §2's banner). This is the executable
half of the DB0 deliverable the design doc calls for -- once DB0 runs it
against real HA (`stable`/`dev`) and writes the ha-api-notes section, any
divergence surfaces here as a failure, not silently.

Auto-marked ``integration`` by ``conftest.py``'s ``pytest_collection_modifyitems``
(everything under ``tests/integration/`` is), so unit CI
(``pytest -m "not integration"``) never touches this file, and it only runs
against ``HASSLE_TEST_HA_URL``/``HASSLE_TEST_HA_TOKEN``.
"""

from __future__ import annotations

from hassle.backend import DirectBackend


def test_dashboard_create_list_update_delete_cycle(ha: DirectBackend) -> None:
    identity = ha.create(
        "dashboard",
        {
            "meta": {
                "url_path": "hassle-test-dash",
                "title": "Hassle Test",
                "icon": "mdi:flask",
            },
            "config": {"views": [{"title": "Overview", "cards": []}]},
        },
    )
    assert identity == "hassle-test-dash"

    remote = ha.list_remote("dashboard")
    assert identity in remote
    assert remote[identity]["meta"]["title"] == "Hassle Test"
    assert remote[identity]["config"]["views"][0]["title"] == "Overview"

    ha.update(
        "dashboard",
        identity,
        {
            "meta": {
                "url_path": "hassle-test-dash",
                "title": "Hassle Test Updated",
                "icon": "mdi:flask",
            },
            "config": {"views": [{"title": "Updated", "cards": []}]},
        },
    )
    updated = ha.list_remote("dashboard")[identity]
    assert updated["meta"]["title"] == "Hassle Test Updated"
    assert updated["config"]["views"][0]["title"] == "Updated"

    ha.delete("dashboard", identity)
    assert identity not in ha.list_remote("dashboard")


def test_default_dashboard_absent_until_created_then_deletable(ha: DirectBackend) -> None:
    # §2.1: a never-customized default dashboard has no config at all --
    # absent from list_remote until someone saves it.
    assert "default" not in ha.list_remote("dashboard")

    identity = ha.create(
        "dashboard",
        {"meta": None, "config": {"views": [{"title": "Home", "cards": []}]}},
    )
    assert identity == "default"
    assert ha.list_remote("dashboard")["default"]["meta"] is None

    ha.delete("dashboard", "default")
    # Reverts to auto-generated -- absent from list_remote again.
    assert "default" not in ha.list_remote("dashboard")


def test_dashboard_tap_action_service_key_survives_verbatim(ha: DirectBackend) -> None:
    # §3.3: normalize_ha must never rewrite a dashboard's `service:` key
    # inside a card action -- pinned against real HA's actual storage
    # behavior (source-informed: believed to save the body verbatim, §2.2
    # item 2).
    card = {
        "type": "tile",
        "entity": "light.kitchen",
        "tap_action": {"action": "call-service", "service": "light.toggle"},
    }
    identity = ha.create(
        "dashboard",
        {
            "meta": {"url_path": "hassle-tap-action", "title": "Tap Action"},
            "config": {"views": [{"title": "Overview", "cards": [card]}]},
        },
    )
    stored = ha.list_remote("dashboard")[identity]["config"]["views"][0]["cards"][0]
    assert stored["tap_action"]["service"] == "light.toggle"
    ha.delete("dashboard", identity)


def test_create_rejects_hyphen_less_url_path(ha: DirectBackend) -> None:
    # §2.2 item 1: HA requires a created dashboard's url_path to contain a
    # hyphen. This assertion is the DB0-pending verification of that
    # hypothesis against a live instance.
    import pytest

    from hassle.backend.errors import HaApiError

    with pytest.raises(HaApiError):
        ha.create(
            "dashboard",
            {
                "meta": {"url_path": "nohyphen", "title": "No Hyphen"},
                "config": {"views": []},
            },
        )
