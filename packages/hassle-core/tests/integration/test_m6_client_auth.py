"""HaClient / DirectBackend basics against a live instance (MILESTONES M6 test 7).

- Auth: a bad token surfaces a clean `HaAuthError` with a fix hint (the
  `hassle login` validation path — DESIGN §4: validity is proven by a call,
  401 ⇒ invalid).
- The live `get_config` populates `DirectBackend.ha_version` and the tested-range
  warning (DESIGN §4, §15).
- A create → list → update → delete cycle works for every managed kind, and
  read-back is in HA's normalized plural storage form (docs/ha-api-notes.md §10.1).
"""

from __future__ import annotations

import os

import pytest

from hassle.backend import DirectBackend
from hassle.backend.errors import HaAuthError


def test_bad_token_raises_clean_auth_error() -> None:
    url = os.environ.get("HASSLE_TEST_HA_URL")
    if not url:
        pytest.skip("needs HASSLE_TEST_HA_URL")
    with (
        pytest.raises(HaAuthError) as excinfo,
        DirectBackend(url, "definitely-not-a-valid-token") as backend,
    ):
        backend.list_remote("automation")
    message = str(excinfo.value)
    # Product-surface error: what / where / fix (R6).
    assert "token" in message.lower()
    assert "hassle login" in message.lower() or "fix" in message.lower()


def test_get_config_populates_version(ha: DirectBackend) -> None:
    assert ha.ha_version
    # A calendar version like "2026.7.1".
    assert ha.ha_version[0].isdigit()
    # version_warning() is None inside the tested range, else a string — never raises.
    warning = ha.version_warning()
    assert warning is None or isinstance(warning, str)


def test_automation_create_list_update_delete(ha: DirectBackend) -> None:
    identity = ha.create(
        "automation",
        {
            "id": "m6_crud",
            "alias": "M6 CRUD",
            "trigger": [{"platform": "state", "entity_id": "input_boolean.x", "to": "on"}],
            "condition": [],
            "action": [
                {"service": "input_boolean.toggle", "target": {"entity_id": "input_boolean.x"}}
            ],
        },
    )
    assert identity == "m6_crud"

    remote = ha.list_remote("automation")
    assert "m6_crud" in remote
    stored = remote["m6_crud"]
    # HA normalizes to the plural schema and service:->action: on storage (§10.1).
    assert "triggers" in stored and "trigger" not in stored
    assert stored["actions"][0].get("action") == "input_boolean.toggle"

    # HA's config API validates the full automation schema on every write, so an
    # update carries a complete config (triggers/conditions/actions), never a
    # partial patch.
    ha.update(
        "automation",
        "m6_crud",
        {
            "id": "m6_crud",
            "alias": "M6 CRUD renamed",
            "trigger": [],
            "condition": [],
            "action": [],
        },
    )
    assert ha.list_remote("automation")["m6_crud"]["alias"] == "M6 CRUD renamed"

    ha.delete("automation", "m6_crud")
    assert "m6_crud" not in ha.list_remote("automation")


def test_script_create_list_update_delete(ha: DirectBackend) -> None:
    identity = ha.create(
        "script",
        {
            "id": "m6_script",
            "alias": "M6 Script",
            "sequence": [
                {"service": "input_boolean.toggle", "target": {"entity_id": "input_boolean.x"}}
            ],
        },
    )
    assert identity == "m6_script"
    stored = ha.list_remote("script")["m6_script"]
    assert stored["sequence"][0].get("action") == "input_boolean.toggle"
    ha.delete("script", "m6_script")
    assert "m6_script" not in ha.list_remote("script")


def test_all_helper_domains_roundtrip(ha: DirectBackend) -> None:
    cases: dict[str, dict[str, object]] = {
        "input_boolean": {"name": "M6 Bool"},
        "input_number": {"name": "M6 Num", "min": 0, "max": 10, "step": 1},
        "input_select": {"name": "M6 Sel", "options": ["a", "b"]},
        "input_text": {"name": "M6 Text"},
        "input_datetime": {"name": "M6 DT", "has_date": True, "has_time": True},
        "input_button": {"name": "M6 Btn"},
        "counter": {"name": "M6 Counter"},
        "timer": {"name": "M6 Timer"},
        "schedule": {"name": "M6 Schedule"},
    }
    for domain, config in cases.items():
        identity = ha.create(domain, config)
        assert identity, f"{domain} create returned no identity"
        listed = ha.list_remote(domain)
        assert identity in listed, f"{domain}:{identity} missing after create"
        ha.update(domain, identity, {**config, "name": f"{config['name']} v2"})
        assert ha.list_remote(domain)[identity]["name"].endswith("v2")
        ha.delete(domain, identity)
        assert identity not in ha.list_remote(domain), f"{domain}:{identity} survived delete"
