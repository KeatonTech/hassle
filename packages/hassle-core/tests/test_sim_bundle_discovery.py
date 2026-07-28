"""Regression: how the `sim` fixture finds the bundle it compiles
(docs/internals/cli.md, "`hassle test`: bundle discovery must not go through
pytest's rootdir").

`_bundle_dir_for` used to return ``Path(request.config.rootpath).parent`` --
"one level above pytest's rootdir", which assumed pytest roots at the
bundle's `tests/` directory. pytest does not derive rootdir from the working
directory; it walks UPWARD from the invocation args looking for a config
anchor, and `hassle init` scaffolds a `pyproject.toml` at the BUNDLE ROOT
(`hassle_cli.uv_project`), which pytest 9 selects as the configfile. rootdir
was therefore the bundle root and `.parent` the bundle's *parent* directory --
so `sim` compiled the tree ABOVE the bundle, importing (and therefore
executing) every unrelated `.py` file sitting next to it.

The fix: discover the bundle the way every `hassle` subcommand already does --
walk up from the test file looking for `hassle.toml`
(`hassle_cli.config.find_bundle_root`'s rule, reimplemented here because
hassle-core must not import hassle-cli) -- and fail with a what/where/fix
error when there is none. The `@pytest.mark.hassle_bundle(path)` marker stays
the explicit override.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hassle.testing.errors import BundleNotFoundError
from hassle.testing.plugin import _bundle_dir_for, pytest_configure
from hassle_dev.snapshots import check_snapshot, normalize_error

SNAP_DIR = Path(__file__).resolve().parent / "snapshots" / "errors"


class _FakeMark:
    def __init__(self, path: Path) -> None:
        self.args = (path,)


class _FakeNode:
    def __init__(self, marker: _FakeMark | None) -> None:
        self._marker = marker

    def get_closest_marker(self, name: str) -> _FakeMark | None:
        return self._marker if name == "hassle_bundle" else None


class _FakeConfig:
    def __init__(self, rootpath: Path) -> None:
        self.rootpath = rootpath


class _FakeRequest:
    """The two attributes `_bundle_dir_for` may read, plus the `config.rootpath`
    it must NOT read: a stub is enough, and keeps this test independent of
    pytest's own internals."""

    def __init__(self, *, path: Path, rootpath: Path, marker: _FakeMark | None = None) -> None:
        self.path = path
        self.node = _FakeNode(marker)
        self.config = _FakeConfig(rootpath)


def _request(**kwargs: object) -> pytest.FixtureRequest:
    return cast("pytest.FixtureRequest", _FakeRequest(**kwargs))  # pyright: ignore[reportArgumentType]


def _make_bundle(root: Path) -> Path:
    """A bundle exactly as `hassle init` scaffolds it: `hassle.toml` and a
    `pyproject.toml` at the root, tests one level below."""
    (root / "tests").mkdir(parents=True)
    (root / "hassle.toml").write_text("format_version = 1\n", encoding="utf-8")
    (root / "pyproject.toml").write_text(
        '[project]\nname = "b"\nversion = "0.0.0"\n', encoding="utf-8"
    )
    test_file = root / "tests" / "test_hallway.py"
    test_file.write_text("", encoding="utf-8")
    return test_file


def test_bundle_is_the_hassle_toml_directory_not_one_above_rootdir(tmp_path: Path) -> None:
    """THE regression: with `hassle init`'s pyproject.toml at the bundle root,
    pytest's rootdir IS the bundle root -- so the old `.parent` fallback
    resolved to `tmp_path`, one level too high."""
    bundle = tmp_path / "bundle"
    test_file = _make_bundle(bundle)

    resolved = _bundle_dir_for(_request(path=test_file, rootpath=bundle))

    assert resolved == bundle
    assert resolved != tmp_path


def test_bundle_discovery_ignores_rootdir_entirely(tmp_path: Path) -> None:
    """Even when pytest roots somewhere unrelated (a monorepo checkout root,
    say), the bundle is the one the test file lives in."""
    bundle = tmp_path / "checkout" / "houses" / "bundle"
    test_file = _make_bundle(bundle)

    resolved = _bundle_dir_for(_request(path=test_file, rootpath=tmp_path / "checkout"))

    assert resolved == bundle


def test_nearest_hassle_toml_wins(tmp_path: Path) -> None:
    """A bundle nested inside another (a monorepo of bundles) resolves to the
    innermost `hassle.toml`, matching `find_bundle_root`."""
    outer = tmp_path / "outer"
    (outer / "tests").mkdir(parents=True)
    (outer / "hassle.toml").write_text("format_version = 1\n", encoding="utf-8")
    inner = outer / "houses" / "inner"
    test_file = _make_bundle(inner)

    assert _bundle_dir_for(_request(path=test_file, rootpath=outer)) == inner


def test_marker_overrides_discovery(tmp_path: Path) -> None:
    """`@pytest.mark.hassle_bundle(path)` still wins -- it is what this repo's
    own simulator tests use, since their bundles live under `fixtures/sim/`."""
    bundle = tmp_path / "bundle"
    test_file = _make_bundle(bundle)
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()

    resolved = _bundle_dir_for(
        _request(path=test_file, rootpath=bundle, marker=_FakeMark(elsewhere))
    )

    assert resolved == elsewhere


def test_no_bundle_raises_what_where_fix(tmp_path: Path) -> None:
    """No `hassle.toml` anywhere above the test file: fail loudly rather than
    guess a directory and compile (execute) whatever Python is in it."""
    stray = tmp_path / "stray"
    stray.mkdir()
    test_file = stray / "test_stray.py"
    test_file.write_text("", encoding="utf-8")

    with pytest.raises(BundleNotFoundError) as excinfo:
        _bundle_dir_for(_request(path=test_file, rootpath=stray))

    msg = str(excinfo.value)
    assert "hassle.toml" in msg  # what
    assert "test_stray.py" in msg  # where
    assert "Fix:" in msg
    check_snapshot(SNAP_DIR, "sim_bundle_not_found", normalize_error(msg))


def test_hassle_bundle_marker_is_registered() -> None:
    """Unregistered markers emit `PytestUnknownMarkWarning` in any bundle that
    doesn't declare them itself -- a scaffolded bundle's pyproject.toml has no
    `[tool.pytest.ini_options] markers`, so the plugin must declare it."""
    recorded: list[tuple[str, str]] = []

    class _ConfigStub:
        def addinivalue_line(self, name: str, line: str) -> None:
            recorded.append((name, line))

    pytest_configure(cast("pytest.Config", _ConfigStub()))  # pyright: ignore[reportArgumentType]

    assert [
        line for name, line in recorded if name == "markers" and line.startswith("hassle_bundle(")
    ]
