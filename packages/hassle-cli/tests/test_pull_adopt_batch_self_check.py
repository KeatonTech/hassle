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
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.sync.models import Plan, PlanAction, PlanEntry
from hassle.sync.source_writer import RecordingSourceWriter
from hassle_cli.pull_apply import DecompiledBatchDoesNotCompileError, apply_pull_with_decompiler


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
    import hassle_cli.pull_apply as pull_apply_mod

    def _broken_decompile_bundle(objects, *, script_refs=None):
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
