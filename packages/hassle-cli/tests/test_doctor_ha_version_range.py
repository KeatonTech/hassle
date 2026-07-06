"""MILESTONES M9 deliverable 4: "HA tested-version range surfaced in `hassle
doctor` (data already exists from M6's version check)".

`hassle doctor` always prints the tested range (offline, no connection
needed -- it's a static constant, R2-safe). A LIVE instance's reported
version is only checked when the caller opts into a connection via
`--sweep-shadows` (the pre-existing connection gate -- `doctor` must never
make network I/O just because `ha_url` happens to be configured), using the
exact `hassle.backend.version.version_warning` logic M6 already wrote.
"""

from __future__ import annotations

from pathlib import Path

from hassle.backend.version import TESTED_HA_MAX, TESTED_HA_MIN


def test_doctor_always_prints_tested_range(bundle_dir: Path, cli) -> None:
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert TESTED_HA_MIN in result.output
    assert TESTED_HA_MAX in result.output


def test_doctor_warns_when_connected_instance_is_outside_tested_range(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    backend.ha_version = "2020.1.0"  # older than TESTED_HA_MIN
    toml_writer(bundle_dir, backend_token=token)
    result = cli(["doctor", "--sweep-shadows"], cwd=bundle_dir)
    assert "2020.1.0" in result.output
    assert "outside the range" in result.output.lower()


def test_doctor_silent_about_version_when_instance_in_range(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    backend, token = fake_backend
    backend.ha_version = "2026.7.0"
    toml_writer(bundle_dir, backend_token=token)
    result = cli(["doctor", "--sweep-shadows"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
    assert "outside the range" not in result.output.lower()


def test_doctor_without_sweep_shadows_never_connects(bundle_dir: Path, cli, toml_writer) -> None:
    """R2: a bare `hassle doctor` (no `--sweep-shadows`) must never attempt a
    connection, even with a real (unreachable-in-tests) `ha_url` configured
    -- it stays a pure offline diagnostic."""
    (bundle_dir / "hassle.toml").write_text(
        'ha_url = "http://homeassistant.local:8123"\nbundle_format = 1\n', encoding="utf-8"
    )
    result = cli(["doctor"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
