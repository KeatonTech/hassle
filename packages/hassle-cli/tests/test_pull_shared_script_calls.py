"""`ux/shared-script-calls` (owner feedback): end-to-end (FakeBackend) `hassle
pull` rewrites a caller's `script.<id>` action to a real function call, with a
cross-file `from scripts.<module> import <fn>` import when the script and its
caller land in different destination files (category-based placement,
DESIGN §7.3, `bundle_ops.default_source_path`).
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
    # files (automations/reminders.py vs scripts/notify.py) -- the shape that
    # actually requires a cross-file import for the rewrite.
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

    automation_file = git_repo / "automations" / "reminders.py"
    script_file = git_repo / "scripts" / "notify.py"
    assert automation_file.is_file(), sorted(p.name for p in (git_repo / "automations").iterdir())
    assert script_file.is_file(), sorted(p.name for p in (git_repo / "scripts").iterdir())

    automation_src = automation_file.read_text(encoding="utf-8")
    assert "from scripts.notify import dismiss_notification" in automation_src
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
