"""DESIGN §6 amendment (owner decision, `ux/pull-organization`): `hassle.toml`
gains an `ignore` array of fnmatch globs on object keys (e.g.
`"input_boolean:material_you_*"`). Purely config-parsing coverage here; the
filtering *semantics* (never adopted/refreshed/deleted, local-declared-but-
ignored warning, manifest migration) are covered in `test_ignore_filtering.py`.
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.config import load_config, write_default_config


def test_load_config_parses_ignore_globs(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text(
        'ha_url = "http://x"\n'
        "format_version = 1\n"
        "mirror = false\n"
        'ignore = ["input_boolean:material_you_*", "sensor:*_debug"]\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.ignore == ["input_boolean:material_you_*", "sensor:*_debug"]


def test_load_config_ignore_defaults_to_empty_list(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text('ha_url = "http://x"\n', encoding="utf-8")
    config = load_config(tmp_path)
    assert config.ignore == []


def test_load_config_missing_file_has_empty_ignore(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.ignore == []


def test_write_default_config_documents_ignore_field(tmp_path: Path) -> None:
    write_default_config(tmp_path)
    content = (tmp_path / "hassle.toml").read_text(encoding="utf-8")
    assert "ignore" in content
