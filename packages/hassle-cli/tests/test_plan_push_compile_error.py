"""`hassle validate` catches `CompileError` and reports it cleanly
(what/where/fix, exit 1, plain + `--json`) -- see
`hassle_cli.cli.validate` and `test_validate_template_helper_compile_error.py`.

But `_build_plan` (shared by `hassle plan`, `hassle status`, and `hassle push`)
called `bundle_ops.compile_local_objects(root)` with no handling at all, so a
bundle that fails to compile (e.g. a `template_number` missing its required
`set_value=`) dumped a raw traceback for those three commands instead of the
same clean report `hassle validate` gives. Proven here via
`CliRunner(catch_exceptions=False)` (the `cli` fixture), which would otherwise
fail these tests with the traceback itself if the CompileError escaped
uncaught.
"""

from __future__ import annotations

import json
from pathlib import Path


def _write_broken_bundle(root: Path, registry_snapshot_json: dict, *, backend_token: str) -> None:
    root.mkdir()
    (root / ".hassle").mkdir()
    (root / ".hassle" / "registry.json").write_text(
        json.dumps(registry_snapshot_json), encoding="utf-8"
    )
    (root / "hassle.toml").write_text(
        f'ha_url = "fake://{backend_token}"\nformat_version = 1\nmirror = false\n',
        encoding="utf-8",
    )
    (root / "helpers.py").write_text(
        """
from hassle import template_number

template_number(
    name="Active HVAC Zones",
    state="{{ states.climate | list | count }}",
    min=0,
    max=8,
    step=1,
)
""",
        encoding="utf-8",
    )


def test_plan_reports_missing_set_value_as_a_clean_error(
    tmp_path: Path, cli, registry_snapshot_json, fake_backend
) -> None:
    _backend, token = fake_backend
    root = tmp_path / "broken-house"
    _write_broken_bundle(root, registry_snapshot_json, backend_token=token)

    result = cli(["plan"], cwd=root)

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "set_value" in result.output
    assert "helpers.py" in result.output


def test_status_reports_missing_set_value_as_a_clean_error(
    tmp_path: Path, cli, registry_snapshot_json, fake_backend
) -> None:
    _backend, token = fake_backend
    root = tmp_path / "broken-house"
    _write_broken_bundle(root, registry_snapshot_json, backend_token=token)

    result = cli(["status"], cwd=root)

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "set_value" in result.output
    assert "helpers.py" in result.output


def test_push_reports_missing_set_value_as_a_clean_error(
    tmp_path: Path, cli, registry_snapshot_json, fake_backend
) -> None:
    _backend, token = fake_backend
    root = tmp_path / "broken-house"
    _write_broken_bundle(root, registry_snapshot_json, backend_token=token)

    result = cli(["push", "--yes"], cwd=root)

    assert result.exit_code == 1
    assert "Traceback" not in result.output
    assert "set_value" in result.output
    assert "helpers.py" in result.output
