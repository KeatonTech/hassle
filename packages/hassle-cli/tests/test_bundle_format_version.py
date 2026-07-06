"""MILESTONES M9 test 4: bundle-format version policy.

`hassle.toml` carries `bundle_format = <int>` (the M9-renamed field --
`hassle_cli.config.BundleConfig` previously called this `format_version`;
see the M9 report for the rename note). The CLI must refuse to operate on a
bundle whose major version is NEWER than what this CLI build understands,
with a clear upgrade error, and must not perform any partial operation
(exit before touching the bundle/manifest/HA at all).
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.config import CURRENT_BUNDLE_FORMAT, load_config


def test_current_format_round_trips(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text(
        f"bundle_format = {CURRENT_BUNDLE_FORMAT}\n", encoding="utf-8"
    )
    config = load_config(tmp_path)
    assert config.bundle_format == CURRENT_BUNDLE_FORMAT


def test_missing_field_defaults_to_1(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text('ha_url = "http://x"\n', encoding="utf-8")
    config = load_config(tmp_path)
    assert config.bundle_format == 1


def test_status_refuses_newer_major_bundle_format(bundle_dir: Path, cli) -> None:
    (bundle_dir / "hassle.toml").write_text(
        f"bundle_format = {CURRENT_BUNDLE_FORMAT + 1}\n", encoding="utf-8"
    )
    result = cli(["status"], cwd=bundle_dir)
    assert result.exit_code != 0
    lowered = result.output.lower()
    assert "bundle_format" in result.output or "bundle format" in lowered
    assert str(CURRENT_BUNDLE_FORMAT + 1) in result.output
    assert "upgrade" in lowered or "newer" in lowered


def test_validate_refuses_newer_major_bundle_format_before_any_work(
    bundle_dir: Path, cli
) -> None:
    """No partial operation: the refusal must happen before compiling/validating
    anything -- a stray success message for any sub-step would mean the CLI
    ran ahead before checking the version gate."""
    (bundle_dir / "hassle.toml").write_text(
        f"bundle_format = {CURRENT_BUNDLE_FORMAT + 5}\n", encoding="utf-8"
    )
    result = cli(["validate"], cwd=bundle_dir)
    assert result.exit_code != 0
    assert "hassle validate:" not in result.output or "upgrade" in result.output.lower()
    assert "no problems found" not in result.output.lower()


def test_older_bundle_format_is_accepted(bundle_dir: Path, cli) -> None:
    """An OLDER (or equal) major is fine -- only NEWER-than-understood refuses."""
    (bundle_dir / "hassle.toml").write_text(
        f"bundle_format = {CURRENT_BUNDLE_FORMAT}\n", encoding="utf-8"
    )
    result = cli(["validate"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output
