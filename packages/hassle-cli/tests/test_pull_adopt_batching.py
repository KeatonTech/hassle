"""Regression for the owner-smoke-test clobber: adopting N objects of one kind
wrote each to the SAME default file via write_whole_file, so only the last
survived (101 adopted, 3 persisted). Adopts targeting one destination file
must be batched into a single multi-object module write.
"""

from __future__ import annotations

from pathlib import Path

from hassle.compiler import compile_bundle


def _seed(backend, kind: str, ident: str, config: dict) -> None:
    backend.create(kind, dict(config, id=ident) if kind != "script" else config)


def test_pull_adopts_all_objects_of_a_kind(git_repo: Path, cli, fake_backend, toml_writer) -> None:
    backend, token = fake_backend
    toml_writer(git_repo, backend_token=token)
    import subprocess

    subprocess.run(["git", "add", "-A"], cwd=git_repo, check=True)
    subprocess.run(["git", "commit", "-qm", "scaffold"], cwd=git_repo, check=True)

    for n in range(1, 4):
        _seed(
            backend,
            "automation",
            f"177000000000{n}",
            {
                "alias": f"Adopted Automation {n}",
                "triggers": [{"trigger": "state", "entity_id": f"binary_sensor.s{n}", "to": "on"}],
                "conditions": [],
                "actions": [{"action": "light.turn_on", "target": {"entity_id": f"light.l{n}"}}],
                "mode": "single",
            },
        )
    for n in range(1, 3):
        _seed(backend, "input_boolean", f"flag_{n}", {"name": f"Flag {n}"})

    result = cli(["pull"], cwd=git_repo)
    assert result.exit_code == 0, result.output

    # THE assertion: everything the backend holds is compilable from disk.
    compiled = compile_bundle(git_repo)
    keys = set(compiled.objects)
    for n in range(1, 4):
        assert f"automation:177000000000{n}" in keys, sorted(keys)
    for n in range(1, 3):
        assert f"input_boolean:flag_{n}" in keys, sorted(keys)


def test_adopt_batching_writes_each_destination_once(tmp_path: Path) -> None:
    from hassle.sync.models import Plan, PlanAction, PlanEntry
    from hassle.sync.source_writer import RecordingSourceWriter
    from hassle_cli.pull_apply import apply_pull_with_decompiler

    def entry(ident: str) -> PlanEntry:
        return PlanEntry(
            object_key=f"automation:{ident}",
            kind="automation",
            action=PlanAction.ADOPT,
            base=None,
            local=None,
            remote={
                "id": ident,
                "alias": f"A {ident}",
                "triggers": [],
                "conditions": [],
                "actions": [],
            },
            remote_hash_at_plan=None,
            source_path="automations/misc.py",
            conflict=None,
        )

    writer = RecordingSourceWriter()
    apply_pull_with_decompiler(Plan(entries=[entry("a1"), entry("a2"), entry("a3")]), writer)

    content = writer.written_files[Path("automations/misc.py")]
    for ident in ("a1", "a2", "a3"):
        assert ident in content, content  # batched: ONE module holding all three
