"""`FakeBackend`'s dashboard-kind behavior (docs/internals/dashboards-design.md
§4.1), mirroring the source-informed HA quirks §2.2 records so the sync
engine gets tested against the same shapes `DirectBackend` will present:

- identity = ``meta.url_path`` verbatim (``meta`` null -> the sentinel
  ``"default"``, §3.1/§2.1);
- ``create`` rejects a hyphen-less ``url_path`` (§2.2 item 1) and a duplicate
  ``url_path``;
- **no normalize-on-write** for the kind (§3.3's guard) -- a `tap_action`
  `service:` key must survive create/update byte-for-byte;
- ``update`` replaces ``meta`` and/or ``config``;
- ``delete`` removes the whole envelope;
- the default dashboard is absent from `list_remote` until created (the
  `config_not_found` analogue, §2.1).

This suite is the FakeBackend half of DB5's "Tests first" list
(docs/internals/dashboards-design.md §12.1's DB5 entry); the DirectBackend
dispatch suite is `test_direct_backend_dashboards.py`.
"""

from __future__ import annotations

import pytest

from hassle.backend.fake import FakeBackend

_TAP_ACTION_CARD = {
    "type": "tile",
    "entity": "light.kitchen",
    "tap_action": {"action": "call-service", "service": "light.toggle"},
}


def _envelope(
    url_path: str | None, *, title: str = "Climate", cards: list[object] | None = None
) -> dict[str, object]:
    meta = None
    if url_path is not None:
        meta = {"url_path": url_path, "title": title, "icon": "mdi:thermostat"}
    return {
        "meta": meta,
        "config": {"views": [{"title": "Overview", "cards": cards or []}]},
    }


def test_create_identity_is_meta_url_path_verbatim() -> None:
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope("climate-control"))
    assert identity == "climate-control"
    assert identity in backend.list_remote("dashboard")


def test_create_with_null_meta_uses_default_sentinel() -> None:
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope(None))
    assert identity == "default"
    assert "default" in backend.list_remote("dashboard")


def test_default_dashboard_absent_from_list_remote_until_created() -> None:
    backend = FakeBackend()
    assert "default" not in backend.list_remote("dashboard")
    backend.create("dashboard", _envelope(None))
    assert "default" in backend.list_remote("dashboard")


def test_create_rejects_hyphen_less_url_path() -> None:
    backend = FakeBackend()
    with pytest.raises(ValueError, match="hyphen"):
        backend.create("dashboard", _envelope("climatecontrol"))
    assert backend.list_remote("dashboard") == {}


def test_create_rejects_duplicate_url_path() -> None:
    backend = FakeBackend()
    backend.create("dashboard", _envelope("climate-control"))
    with pytest.raises(ValueError, match="climate-control"):
        backend.create("dashboard", _envelope("climate-control", title="Different"))


def test_create_rejects_duplicate_default() -> None:
    backend = FakeBackend()
    backend.create("dashboard", _envelope(None))
    with pytest.raises(ValueError, match="default"):
        backend.create("dashboard", _envelope(None))


def test_create_rejects_url_path_literally_named_default() -> None:
    """Should-fix 3(a) regression: the hyphen exemption must be keyed off
    ``meta is None`` (the actual default-dashboard marker), never off the
    derived identity STRING -- a real, non-default dashboard whose declared
    `url_path` happens to be the string "default" is not exempt from HA's
    unconditional hyphen rule."""
    backend = FakeBackend()
    with pytest.raises(ValueError, match="hyphen"):
        backend.create(
            "dashboard",
            {"meta": {"url_path": "default", "title": "Not The Default"}, "config": {"views": []}},
        )


def test_create_does_not_normalize_tap_action_service_key() -> None:
    # §3.3: normalize_ha's generic service:->action: rewrite must never touch
    # a dashboard body -- a card's tap_action legitimately uses the legacy
    # `service:` key (§2.2 item 5) and must survive byte-for-byte.
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope("climate-control", cards=[_TAP_ACTION_CARD]))
    stored = backend.list_remote("dashboard")[identity]
    card = stored["config"]["views"][0]["cards"][0]
    assert card["tap_action"] == {"action": "call-service", "service": "light.toggle"}


def test_update_does_not_normalize_tap_action_service_key() -> None:
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope("climate-control"))
    backend.update(
        "dashboard",
        identity,
        _envelope("climate-control", cards=[_TAP_ACTION_CARD]),
    )
    stored = backend.list_remote("dashboard")[identity]
    card = stored["config"]["views"][0]["cards"][0]
    assert card["tap_action"] == {"action": "call-service", "service": "light.toggle"}


def test_update_replaces_meta_and_config() -> None:
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope("climate-control", title="Climate"))
    backend.update(
        "dashboard",
        identity,
        _envelope("climate-control", title="Climate V2", cards=[{"type": "markdown"}]),
    )
    stored = backend.list_remote("dashboard")[identity]
    assert stored["meta"]["title"] == "Climate V2"
    assert stored["config"]["views"][0]["cards"] == [{"type": "markdown"}]


def test_update_raises_for_unknown_non_default_dashboard() -> None:
    """Should-fix 3(b) regression: `DirectBackend` raises when an UPDATE
    targets a `url_path` with no known registry item (`_aresolve_dashboard_id`)
    -- `FakeBackend` silently upserted instead, a fidelity gap that would let
    a rollback-recreates-via-update mistake (the same bug class the
    HELPER_DOMAINS guard above already exists to catch) pass unnoticed for
    dashboards specifically."""
    backend = FakeBackend()
    with pytest.raises(ValueError, match="climate-control"):
        backend.update(
            "dashboard",
            "climate-control",
            _envelope("climate-control"),
        )


def test_update_upserts_default_dashboard_even_if_not_yet_created() -> None:
    # The default dashboard is EXEMPT from the missing-identity guard: real
    # HA's `lovelace/config/save(url_path=null)` genuinely upserts it (there
    # is no registry item that could ever be "missing").
    backend = FakeBackend()
    backend.update("dashboard", "default", _envelope(None))
    assert "default" in backend.list_remote("dashboard")


def test_delete_removes_whole_envelope() -> None:
    backend = FakeBackend()
    identity = backend.create("dashboard", _envelope("climate-control"))
    backend.delete("dashboard", identity)
    assert identity not in backend.list_remote("dashboard")


def test_delete_default_reverts_to_absent() -> None:
    backend = FakeBackend()
    backend.create("dashboard", _envelope(None))
    backend.delete("dashboard", "default")
    assert "default" not in backend.list_remote("dashboard")


def test_writes_tracked_for_dashboard_create_update_delete() -> None:
    backend = FakeBackend()
    assert backend.writes_since_reset() == 0
    identity = backend.create("dashboard", _envelope("climate-control"))
    assert backend.writes_since_reset() == 1
    backend.update("dashboard", identity, _envelope("climate-control", title="V2"))
    assert backend.writes_since_reset() == 2
    backend.delete("dashboard", identity)
    assert backend.writes_since_reset() == 3
