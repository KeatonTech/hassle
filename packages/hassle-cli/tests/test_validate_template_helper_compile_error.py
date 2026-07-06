"""Reviewer follow-up (M10 merge): a `template_number`/`template_select`
declaration missing its required write-target kwarg (`set_value=`/
`select_option=`) used to only fail at APPLY time with a bare backend
`ValueError` -- `hassle validate` would happily report "no findings" on a
bundle that was guaranteed to fail on push.

`MissingTemplateHelperWriteTargetError` (a `hassle.compiler.errors.CompileError`)
now makes this a compile-time error, raised from the DSL builder itself
(`hassle.compiler.template_helpers._declare_template_helper`). Since
`compile_bundle` runs before `validate_bundle`'s tier-2/3 checks even start,
`hassle validate` must report this cleanly (exit 1, the error's own
what/where/fix message on stderr/stdout) instead of letting the exception
escape as a raw traceback -- proven here via `CliRunner(catch_exceptions=False)`
(the `cli` fixture), which would otherwise fail the test with the traceback
itself.
"""

from __future__ import annotations

from pathlib import Path


def _write_bundle(root: Path, registry_snapshot_json: dict) -> None:
    import json

    root.mkdir()
    (root / ".hassle").mkdir()
    (root / ".hassle" / "registry.json").write_text(
        json.dumps(registry_snapshot_json), encoding="utf-8"
    )
    (root / "hassle.toml").write_text("format_version = 1\nmirror = false\n", encoding="utf-8")


def test_validate_reports_missing_set_value_as_a_clean_finding(
    tmp_path: Path, cli, registry_snapshot_json
) -> None:
    root = tmp_path / "broken-house"
    _write_bundle(root, registry_snapshot_json)
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
    result = cli(["validate"], cwd=root)
    assert result.exit_code == 1
    assert "set_value" in result.output
    assert "helpers.py" in result.output


def test_validate_json_reports_missing_select_option_with_file_line(
    tmp_path: Path, cli, registry_snapshot_json
) -> None:
    import json

    root = tmp_path / "broken-house"
    _write_bundle(root, registry_snapshot_json)
    (root / "helpers.py").write_text(
        """
from hassle import template_select

template_select(
    name="House Scene",
    state="{{ states('input_select.house_mode') }}",
    options="{{ ['home', 'away', 'night'] }}",
)
""",
        encoding="utf-8",
    )
    result = cli(["validate", "--json"], cwd=root)
    assert result.exit_code == 1, result.output
    payload = json.loads(result.output)
    assert set(payload) == {"findings"}
    assert len(payload["findings"]) == 1
    finding = payload["findings"][0]
    assert set(finding) == {"code", "severity", "file", "line", "message", "fix"}
    assert finding["file"] == "helpers.py"
    assert isinstance(finding["line"], int)
    assert "select_option" in finding["message"]
