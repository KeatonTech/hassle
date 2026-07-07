"""`ux/shared-script-calls` (owner feedback): end-to-end (FakeBackend) `hassle
pull` rewrites a caller's `script.<id>` action to a real function call, with a
cross-file `from <module> import <fn>` import when the script and its
caller land in different destination files (category-based placement,
DESIGN §7.3, `bundle_ops.default_source_path`; MILESTONES M15 work item B:
root-level, cross-kind file layout).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from hassle.compiler import compile_bundle


def _commit_toml_change(bundle: Path) -> None:
    subprocess.run(["git", "add", "-A"], cwd=bundle, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=bundle,
        check=True,
        capture_output=True,
    )


def test_pull_rewrites_cross_file_script_call_with_import(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "script",
        {
            "alias": "Dismiss notification",
            "fields": {"notification_id": {"default": ""}},
            "sequence": [
                {
                    "service": "persistent_notification.dismiss",
                    "data": {"notification_id": "{{ notification_id }}"},
                }
            ],
        },
    )
    backend.create(
        "automation",
        {
            "id": "dismiss_reminder_automation",
            "alias": "Dismiss guest reminder",
            "triggers": [
                {"trigger": "state", "entity_id": ["input_boolean.guest_mode"], "to": "off"}
            ],
            "conditions": [],
            "actions": [
                {
                    "action": "script.dismiss_notification",
                    "data": {"notification_id": "guest_reminder"},
                    "metadata": {},
                }
            ],
            "mode": "single",
        },
    )

    # Distinct categories so the two objects land in different destination
    # files (reminders.py vs notify.py) -- the shape that actually requires a
    # cross-file import for the rewrite.
    snapshot = backend.registry_snapshot
    snapshot.categories["automation"] = {"reminders": "Reminders"}
    snapshot.categories["script"] = {"notify": "Notify"}
    entity_cls = type(snapshot.entities[0])
    snapshot.entities.append(
        entity_cls.model_validate(
            {
                "entity_id": "automation.dismiss_reminder_automation",
                "unique_id": "dismiss_reminder_automation",
                "domain": "automation",
                "categories": {"automation": "reminders"},
            }
        )
    )
    snapshot.entities.append(
        entity_cls.model_validate(
            {
                "entity_id": "script.dismiss_notification",
                "unique_id": "dismiss_notification",
                "domain": "script",
                "categories": {"script": "notify"},
            }
        )
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    automation_file = git_repo / "reminders.py"
    script_file = git_repo / "notify.py"
    assert automation_file.is_file(), sorted(p.name for p in git_repo.iterdir())
    assert script_file.is_file(), sorted(p.name for p in git_repo.iterdir())

    automation_src = automation_file.read_text(encoding="utf-8")
    assert "from notify import dismiss_notification" in automation_src
    assert 'dismiss_notification(notification_id="guest_reminder", metadata={})' in automation_src
    assert "script.dismiss_notification" not in automation_src

    script_src = script_file.read_text(encoding="utf-8")
    assert "@shared_script(" in script_src

    compiled = compile_bundle(git_repo)
    assert "automation:dismiss_reminder_automation" in compiled.objects
    assert "script:dismiss_notification" in compiled.objects
    recompiled_call = compiled.objects["automation:dismiss_reminder_automation"].to_ha()["actions"][
        0
    ]
    assert recompiled_call["action"] == "script.dismiss_notification"
    assert recompiled_call["data"] == {"notification_id": "guest_reminder"}
    assert recompiled_call["metadata"] == {}


def test_pull_rewrites_rich_field_script_call_same_batch(
    git_repo: Path, cli, fake_backend, toml_writer
) -> None:
    """`ux/shared-script-rich-fields`, task 3: a script whose every field
    carries `selector`/`name`/`description` (the shape the HA UI always
    saves, mirroring `call_to_action_notification`) is called by an
    automation in the SAME pull batch -- the widened emit decision must
    still pick `@shared_script` (not fall back to `@script`), and the caller
    rewrite must still fire.

    MILESTONES M15 work item B: both objects here are uncategorized, so they
    both land in the SAME shared root-level `misc.py` (mixed-kind) -- this is
    now a same-FILE call (no import needed at all), not just a same-batch
    one. `test_pull_rewrites_cross_file_script_call_with_import` above is the
    genuinely cross-FILE case (distinct categories -> distinct destination
    files)."""
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    _commit_toml_change(git_repo)

    backend.create(
        "script",
        {
            "alias": "Call to action notification",
            "fields": {
                "title": {"name": "Title", "selector": {"text": {}}},
                "message": {"name": "Message", "selector": {"text": {}}},
                "action_button": {"name": "Action button", "selector": {"text": {}}},
                "action_button_icon": {"name": "Action button icon", "selector": {"text": {}}},
                "tag": {"name": "Tag", "selector": {"text": {}}},
            },
            "sequence": [
                {
                    "service": "notify.mobile_app_keaton",
                    "data": {
                        "title": "{{ title }}",
                        "message": "{{ message }}",
                        "tag": "{{ tag }}",
                        "action_button": "{{ action_button }}",
                        "action_button_icon": "{{ action_button_icon }}",
                    },
                }
            ],
        },
    )
    backend.create(
        "automation",
        {
            "id": "garage_door_opened_notify",
            "alias": "Garage door opened notify",
            "triggers": [{"trigger": "state", "entity_id": ["cover.garage_door"], "to": ["open"]}],
            "conditions": [],
            "actions": [
                {
                    "action": "script.call_to_action_notification",
                    "data": {
                        "title": "Garage",
                        "message": "Door opened",
                        "action_button": "view",
                        "action_button_icon": "mdi:garage-open",
                        "tag": "garage_door",
                    },
                    "metadata": {},
                }
            ],
            "mode": "single",
        },
    )

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # Both objects are uncategorized -> the SAME shared root-level misc.py.
    misc_src = (git_repo / "misc.py").read_text(encoding="utf-8")

    assert "@shared_script(" in misc_src
    assert "@script(" not in misc_src
    assert "fields={" in misc_src
    assert "call_to_action_notification(" in misc_src
    assert "script.call_to_action_notification" not in misc_src

    compiled = compile_bundle(git_repo)
    recompiled_call = compiled.objects["automation:garage_door_opened_notify"].to_ha()["actions"][0]
    assert recompiled_call["action"] == "script.call_to_action_notification"
    assert recompiled_call["data"] == {
        "title": "Garage",
        "message": "Door opened",
        "action_button": "view",
        "action_button_icon": "mdi:garage-open",
        "tag": "garage_door",
    }
    assert recompiled_call["metadata"] == {}
