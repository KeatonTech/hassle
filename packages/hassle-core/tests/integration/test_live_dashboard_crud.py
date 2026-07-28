"""Dashboard CRUD against real HA (docs/internals/dashboards-design.md
§4.1/§9.2).

**DB0 COMPLETE (2026-07-27)**: every wire shape this suite asserts
(`lovelace/dashboards/*`, `lovelace/config*`) has been captured against a
live HA **2026.7.4** and written up in docs/internals/ha-api-notes.md
§39.1-§39.8, with raw request/response pairs in
`docs/ha-api-captures/dashboards-db0.json`. All four tests below pass
there. This suite is now the standing guard: a divergence on a future HA
release surfaces here as a failure, not silently.

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
    # hyphen -- confirmed live (ha-api-notes §39.3): `invalid_format`, "Url
    # path needs to contain a hyphen (-)". Hassle never sends the
    # `allow_single_word: true` flag that would bypass it.
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


def test_update_converges_against_real_ha_registry_merge(ha: DirectBackend) -> None:
    """DB0 runbook item 11 / ha-api-notes §39.1: the end-to-end convergence
    loop the fakes could not honestly simulate.

    HA's dashboard registry MERGES an update into the stored item rather than
    replacing it, so a field only clears when it is sent explicitly. Push a
    dashboard WITH an icon, clear the icon locally, push again, and read back:
    the remote must now EQUAL the local desired state. If it does not,
    `_advance_manifest` records an unchanged remote as the new base and every
    subsequent `hassle push` re-plans the same no-op update forever.
    """
    identity = ha.create(
        "dashboard",
        {
            "meta": {
                "url_path": "hassle-converge",
                "title": "Converge",
                "icon": "mdi:flask",
            },
            "config": {"views": [{"title": "Overview", "cards": []}]},
        },
    )
    try:
        assert ha.list_remote("dashboard")[identity]["meta"]["icon"] == "mdi:flask"

        # The icon is deleted locally -- `meta` simply no longer carries it.
        desired = {
            "meta": {
                "url_path": "hassle-converge",
                "title": "Converge",
                "show_in_sidebar": True,
                "require_admin": False,
            },
            "config": {"views": [{"title": "Overview", "cards": []}]},
        }
        ha.update("dashboard", identity, desired)

        remote = ha.list_remote("dashboard")[identity]
        # §39.1: HA drops the key outright -- it never stores a literal null,
        # so the remote `meta` is byte-equal to the desired one.
        assert "icon" not in remote["meta"]
        assert remote["meta"] == desired["meta"]
        assert remote["config"] == desired["config"]

        # Convergence: a second identical push leaves the remote untouched.
        ha.update("dashboard", identity, desired)
        assert ha.list_remote("dashboard")[identity] == remote
    finally:
        ha.delete("dashboard", identity)


def test_default_dashboard_is_not_adopted_twice(ha: DirectBackend) -> None:
    """DB0 / ha-api-notes §39.2 (BLOCKER), guarded against real HA.

    Whatever this instance's default dashboard looks like -- migrated to a
    `url_path: "lovelace"` registry item (HA 2026.x) or still reachable only
    as `url_path=null` -- `list_remote` must report it exactly ONCE. Adopting
    it under both identities means one HA dashboard becomes two Hassle
    objects that silently overwrite each other on every push.
    """
    ha.create(
        "dashboard",
        {"meta": None, "config": {"views": [{"title": "Home", "cards": []}]}},
    )
    remote = ha.list_remote("dashboard")
    try:
        assert not ("default" in remote and "lovelace" in remote), (
            f"the default dashboard was adopted under BOTH identities: {sorted(remote)}"
        )
        assert "default" in remote or "lovelace" in remote
    finally:
        for candidate in ("default", "lovelace"):
            if candidate in remote:
                ha.delete("dashboard", candidate)
