"""`ux/shared-script-calls-fix` (coordinator task 4): can a BATCH-level
self-check (compile just the objects going into one destination file, before
writing it) catch a decompiler coordination bug earlier/more precisely than
the CLI-level whole-bundle backstop (`test_pull_post_write_compile_backstop.py`)?

Decision (documented here and in `pull_apply.py`): YES for `_adopt_batch`
(whole-file, multi-object writes) -- it's cheap (one `compile_bundle` call
over a small temp directory, no different in kind from what the CLI backstop
already does for the whole bundle) and it (a) fires BEFORE any file is
written or the manifest is touched, and (b) can name the exact destination
file/object set that failed, which the whole-bundle backstop can't distinguish
from any other file in a multi-file pull. NOT extended to `_refresh` (single
object LibCST splice): the spliced object's cross-file calls depend on
another file's real content, which isn't available in isolation, so a
same-file-only self-check there would be incomplete without also being
misleadingly reassuring -- the CLI-level whole-bundle backstop remains the
correct (and sufficient) backstop for that path.

**Value-comparison widening, then a field-failure fix (``ux/dsl-ergonomics``
item 4, then ``fix/self-check-value-compare``):** the self-check was widened
to compare recompiled VALUES against the original stored config, not just
"does it compile" (`test_adopt_batch_self_check_catches_value_mismatch_that_
still_compiles` -- the true-positive case, the `for_each` template-string
bug). The FIRST value-comparison mechanism (decompiled DSL TEXT) was itself
buggy: it wasn't context-free, and false-positived on the owner's live bundle
(`test_adopt_batch_self_check_does_not_false_positive_on_batch_context_text_
diff` -- pins the fix: a name-collision `_2` suffix or a same-batch
script-call rewrite changes decompiled TEXT without changing the underlying
HA value, and the self-check must not care). `test_owner_bundle_shape_class_
pulls_clean_via_cli` is the end-to-end reproduction of the owner's actual
reported shape (helpers + an automation calling a same-batch shared script)
via the real CLI + `FakeBackend`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.sync.models import Plan, PlanAction, PlanEntry
from hassle.sync.pull_apply import (
    DecompiledBatchDoesNotCompileError,
    DecompiledValueMismatchError,
    apply_pull_with_decompiler,
)
from hassle.sync.source_writer import RecordingSourceWriter


def _adopt_entry(object_key: str, kind: str, remote: dict, source_path: str) -> PlanEntry:
    return PlanEntry(
        object_key=object_key,
        kind=kind,
        action=PlanAction.ADOPT,
        base=None,
        local=None,
        remote=remote,
        remote_hash_at_plan=None,
        source_path=source_path,
        conflict=None,
    )


def test_adopt_batch_self_check_catches_broken_decompile_before_writing(monkeypatch) -> None:
    from hassle.sync import pull_apply as pull_apply_mod

    def _broken_decompile_bundle(objects, *, script_refs=None, snapshot=None):
        return (
            "from hassle import *\n\n"
            "from hassle.registry import entities as e\n\n\n"
            "@automation(id='a1', alias='x')\n"
            "def a1():\n"
            "    raise RuntimeError('simulated decompiler coordination bug')\n"
        )

    monkeypatch.setattr(pull_apply_mod, "decompile_bundle", _broken_decompile_bundle)

    entries = [
        _adopt_entry(
            "automation:a1",
            "automation",
            {"id": "a1", "alias": "A1", "triggers": [], "conditions": [], "actions": []},
            "automations/misc.py",
        )
    ]
    writer = RecordingSourceWriter()

    with pytest.raises(DecompiledBatchDoesNotCompileError) as excinfo:
        apply_pull_with_decompiler(Plan(entries=entries), writer)

    # Names the destination file (what/where), and never wrote it.
    assert "automations/misc.py" in str(excinfo.value)
    assert Path("automations/misc.py") not in writer.written_files


def test_adopt_batch_self_check_is_silent_for_healthy_batch() -> None:
    entries = [
        _adopt_entry(
            "automation:a1",
            "automation",
            {"id": "a1", "alias": "A1", "triggers": [], "conditions": [], "actions": []},
            "automations/misc.py",
        )
    ]
    writer = RecordingSourceWriter()

    apply_pull_with_decompiler(Plan(entries=entries), writer)  # must not raise

    assert "a1" in writer.written_files[Path("automations/misc.py")]


def test_adopt_batch_self_check_catches_value_mismatch_that_still_compiles(monkeypatch) -> None:
    """``ux/dsl-ergonomics``, item 4 investigation: the "does it compile" self-check
    alone would NOT have caught the real `for_each` template-string bug, because
    `list("{{ template }}")` compiles just fine -- it just silently produces the
    wrong value (a list of individual characters instead of the template string).
    This pins the WIDENED self-check (comparing the recompiled value's canonical
    hash against the original stored config) against a hand-rolled fake decompiler
    that reproduces exactly that failure mode: valid Python, wrong meaning.
    """
    from hassle.sync import pull_apply as pull_apply_mod

    def _silently_wrong_decompile_bundle(objects, *, script_refs=None, snapshot=None):
        # Reproduces the shape of the real bug: a `repeat.for_each` that should be
        # the template string verbatim instead gets exploded into a character list
        # -- valid Python, compiles cleanly, but a different value than the input.
        return (
            "from hassle import *\n\n"
            "from hassle.registry import entities as e\n\n\n"
            "@automation(id='a1', alias='A1')\n"
            "def a1():\n"
            "    with repeat_for_each(list('{{ x }}')):\n"
            '        service("light.turn_on")\n'
        )

    monkeypatch.setattr(pull_apply_mod, "decompile_bundle", _silently_wrong_decompile_bundle)

    entries = [
        _adopt_entry(
            "automation:a1",
            "automation",
            {
                "id": "a1",
                "alias": "A1",
                "triggers": [],
                "conditions": [],
                "actions": [
                    {
                        "repeat": {
                            "for_each": "{{ x }}",
                            "sequence": [{"action": "light.turn_on"}],
                        }
                    }
                ],
            },
            "automations/misc.py",
        )
    ]
    writer = RecordingSourceWriter()

    with pytest.raises(DecompiledValueMismatchError) as excinfo:
        apply_pull_with_decompiler(Plan(entries=entries), writer)

    assert "automation:a1" in str(excinfo.value)
    # Nothing written -- this fires before any adopt destination is touched.
    assert Path("automations/misc.py") not in writer.written_files


def test_adopt_batch_self_check_does_not_false_positive_on_batch_context_text_diff(
    monkeypatch,
) -> None:
    """Field-failure fix (coordinator report, `fix/self-check-value-compare`):
    the self-check's comparison must be context-free -- it must not care that
    the SAME object's decompiled TEXT differs between the real batch context
    (name-collision `_2` dedup suffix, or a same-batch script-call rewrite)
    and a solo re-decompile of the original config (fresh naming, no resolver).
    Reproduced here with a hand-rolled fake `decompile_bundle`: the batch
    output uses a `_2`-suffixed function name (as a real batch would, when a
    second object's alias collides) for `automation:a1`, but a solo
    `decompile_object` of the SAME stored config always names it fresh
    (`a1`, no collision partner) -- a pure Python-identifier difference that
    can never appear in `to_ha()` (the function name is not part of the HA
    value at all). The OLD text-comparison self-check would have treated
    this as a value mismatch and blocked the whole batch (the coordinator's
    field failure: six objects refused, only one of which -- if any --
    was a real problem); the value-comparison self-check must not.
    """
    from hassle.sync import pull_apply as pull_apply_mod

    def _batch_context_name_collision_decompile_bundle(objects, *, script_refs=None, snapshot=None):
        # Simulates what a real batch compile would emit when a SIBLING
        # object's alias collides and forces this one to a `_2` suffix --
        # the value (`to_ha()`) is untouched, only the Python identifier.
        return (
            "from hassle import *\n\n"
            "from hassle.registry import entities as e\n\n\n"
            "@automation(id='a1', alias='A1')\n"
            "def a1_2():\n"
            '    service("light.turn_on")\n'
        )

    monkeypatch.setattr(
        pull_apply_mod, "decompile_bundle", _batch_context_name_collision_decompile_bundle
    )

    entries = [
        _adopt_entry(
            "automation:a1",
            "automation",
            {
                "id": "a1",
                "alias": "A1",
                "triggers": [],
                "conditions": [],
                "actions": [{"action": "light.turn_on"}],
            },
            "automations/misc.py",
        )
    ]
    writer = RecordingSourceWriter()

    apply_pull_with_decompiler(Plan(entries=entries), writer)  # must NOT raise

    assert "a1_2" in writer.written_files[Path("automations/misc.py")]


def test_owner_bundle_shape_class_pulls_clean_via_cli(
    git_repo, cli, fake_backend, toml_writer
) -> None:
    """End-to-end (real CLI + FakeBackend, no monkeypatching): the owner's
    actual reported shape class -- an automation with a same-batch
    shared-script call, adopted together with five sibling helpers (two
    `input_datetime`, two `input_number`, one `input_text`) in one pull --
    must pull clean. This is the exact class of object the field failure
    blocked (six objects refused; `hassle pull` left the owner's bundle
    empty). Fixed via `values_match`'s context-free canonical-JSON
    comparison (`fix/self-check-value-compare`)."""
    import subprocess

    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "point at fake backend"],
        cwd=git_repo,
        check=True,
        capture_output=True,
    )

    backend.create(
        "input_datetime", {"name": "Notification Shown At", "has_date": True, "has_time": True}
    )
    backend.create(
        "input_datetime", {"name": "Notification Dismissed At", "has_date": True, "has_time": True}
    )
    backend.create("input_number", {"name": "Notification Count", "min": 0, "max": 100, "step": 1})
    backend.create(
        "input_number", {"name": "Notification Retry Count", "min": 0, "max": 10, "step": 1}
    )
    backend.create("input_text", {"name": "Last Shown Notification", "max": 255})
    backend.create(
        "script",
        {
            "alias": "Dismiss notification",
            "fields": {"notification_id": {"default": ""}},
            "sequence": [
                {
                    "action": "persistent_notification.dismiss",
                    "data": {"notification_id": "{{ notification_id }}"},
                }
            ],
        },
    )
    backend.create(
        "automation",
        {
            "id": "1776572725931",
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

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output
    for expected in (
        "adopt  automation:1776572725931",
        "adopt  input_datetime:notification_dismissed_at",
        "adopt  input_datetime:notification_shown_at",
        "adopt  input_number:notification_count",
        "adopt  input_number:notification_retry_count",
        "adopt  input_text:last_shown_notification",
        "adopt  script:dismiss_notification",
    ):
        assert expected in result.output, result.output
