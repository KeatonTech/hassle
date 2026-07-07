"""MILESTONES M17: `hassle.toml` gains a `toolchain_path` key (config-surface
addition) -- the highest-priority entry in `hassle_cli.uv_project`'s
toolchain resolution order. Purely config load/persist coverage here; the
resolution-order semantics themselves are covered in
`test_uv_project_scaffold.py`.
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.config import load_config, persist_toolchain_path, write_default_config


def test_load_config_parses_toolchain_path(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text(
        'ha_url = "http://x"\nbundle_format = 2\ntoolchain_path = "/home/me/hassle"\n',
        encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.toolchain_path == "/home/me/hassle"


def test_load_config_toolchain_path_defaults_to_none(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text('ha_url = "http://x"\n', encoding="utf-8")
    config = load_config(tmp_path)
    assert config.toolchain_path is None


def test_load_config_missing_file_has_none_toolchain_path(tmp_path: Path) -> None:
    config = load_config(tmp_path)
    assert config.toolchain_path is None


def test_persist_toolchain_path_writes_new_line(tmp_path: Path) -> None:
    write_default_config(tmp_path)
    persist_toolchain_path(tmp_path, "/home/me/hassle")
    config = load_config(tmp_path)
    assert config.toolchain_path == "/home/me/hassle"


def test_persist_toolchain_path_replaces_existing_line_preserving_others(tmp_path: Path) -> None:
    (tmp_path / "hassle.toml").write_text(
        '# a comment\nha_url = "http://x"\ntoolchain_path = "/old/path"\nmirror = false\n',
        encoding="utf-8",
    )

    persist_toolchain_path(tmp_path, "/new/path")

    text = (tmp_path / "hassle.toml").read_text(encoding="utf-8")
    assert "/old/path" not in text
    assert "/new/path" in text
    assert "# a comment" in text
    assert 'ha_url = "http://x"' in text
    assert "mirror = false" in text
    config = load_config(tmp_path)
    assert config.toolchain_path == "/new/path"


def test_persist_toolchain_path_creates_file_if_missing(tmp_path: Path) -> None:
    persist_toolchain_path(tmp_path, "/some/path")
    config = load_config(tmp_path)
    assert config.toolchain_path == "/some/path"
