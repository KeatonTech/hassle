"""Guards the corpus-stats CI gate: it must accept the real corpus and reject gaps."""

from __future__ import annotations

import json
from pathlib import Path

from hassle_dev.corpus import analyze, find_configs_dir


def test_real_corpus_satisfies_contract() -> None:
    configs = find_configs_dir(Path(__file__).parent)
    assert configs is not None, "fixtures/configs not found"
    report = analyze(configs)
    assert report.total >= 40
    assert report.ok(), f"corpus gaps: {report.missing()}"


def test_incomplete_corpus_reports_gaps(tmp_path: Path) -> None:
    # A lone automation is nowhere near the contract.
    (tmp_path / "automation_only.json").write_text(
        json.dumps({"id": "a", "trigger": [{"platform": "state"}], "action": []}),
        encoding="utf-8",
    )
    report = analyze(tmp_path)
    gaps = report.missing()
    assert "fixtures" in gaps  # < 40
    assert "helper_domains" in gaps
    assert "modes" in gaps
    assert not report.ok()
