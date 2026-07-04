"""`hassle-dev decompile-coverage` — machine-readable coverage artifact (M2).

Wired into CI as the >= 90% gate: the command analyzes the full fixture corpus,
writes a JSON artifact listing per-fixture `raw_*` node counts, and exits
non-zero if the clean fraction is below the gate.
"""

from __future__ import annotations

import json
from pathlib import Path

from hassle_dev.cli import main


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def test_decompile_coverage_writes_json_artifact(tmp_path: Path) -> None:
    out_file = tmp_path / "coverage.json"
    exit_code = main(
        [
            "decompile-coverage",
            "--configs",
            str(_repo_root() / "fixtures" / "configs"),
            "--out",
            str(out_file),
        ]
    )
    assert exit_code == 0
    report = json.loads(out_file.read_text(encoding="utf-8"))
    assert "total_objects" in report
    assert "clean_fraction" in report
    assert "exceptions" in report
    assert isinstance(report["exceptions"], list)
    assert report["clean_fraction"] >= 0.90


def test_decompile_coverage_fails_gate_when_forced_low(tmp_path: Path) -> None:
    # A configs dir containing only device-trigger-shaped (raw-only) fixtures
    # cannot meet the 90% gate; the command must report failure (exit 1), not
    # silently pass.
    configs_dir = tmp_path / "configs"
    configs_dir.mkdir()
    (configs_dir / "automation_device_only.json").write_text(
        json.dumps(
            {
                "id": "device_only",
                "alias": "Device only",
                "triggers": [{"trigger": "device", "device_id": "abc123", "domain": "sensor"}],
                "actions": [{"action": "light.turn_on", "target": {"entity_id": "light.x"}}],
                "mode": "single",
            }
        ),
        encoding="utf-8",
    )
    out_file = tmp_path / "coverage.json"
    exit_code = main(["decompile-coverage", "--configs", str(configs_dir), "--out", str(out_file)])
    assert exit_code == 1
    report = json.loads(out_file.read_text(encoding="utf-8"))
    assert report["clean_fraction"] < 0.90
    assert report["exceptions"]
