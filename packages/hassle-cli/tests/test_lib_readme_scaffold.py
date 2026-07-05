"""`hassle init` (and `hassle pull`, when it creates the scaffold dirs) writes
`lib/README.md` explaining the `lib/` directory (DESIGN §5.6/§6: macros with
`@macro`, shared scripts with `@shared_script`, plain constants; imported via
`from lib.x import y`) plus a one-line `tests/README.md` when `tests/` is
otherwise empty. Both writes are idempotent -- never overwrite a file the user
may have edited.
"""

from __future__ import annotations

from pathlib import Path

from hassle_cli.init_cmd import init_bundle


def test_init_writes_lib_readme(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    readme = tmp_path / "lib" / "README.md"
    assert readme.is_file()
    content = readme.read_text(encoding="utf-8")
    assert "@macro" in content
    assert "@shared_script" in content
    assert "from lib." in content


def test_init_writes_tests_readme_when_tests_dir_empty(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    readme = tmp_path / "tests" / "README.md"
    assert readme.is_file()


def test_init_does_not_overwrite_existing_lib_readme(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    custom = "# My own notes\nDon't touch this.\n"
    (tmp_path / "lib" / "README.md").write_text(custom, encoding="utf-8")

    init_bundle(tmp_path)  # re-run, idempotent

    assert (tmp_path / "lib" / "README.md").read_text(encoding="utf-8") == custom


def test_init_does_not_overwrite_existing_tests_readme(tmp_path: Path) -> None:
    init_bundle(tmp_path)
    custom = "# Custom test notes\n"
    (tmp_path / "tests" / "README.md").write_text(custom, encoding="utf-8")

    init_bundle(tmp_path)

    assert (tmp_path / "tests" / "README.md").read_text(encoding="utf-8") == custom


def test_init_does_not_write_tests_readme_when_tests_dir_already_has_content(
    tmp_path: Path,
) -> None:
    # A bundle whose tests/ already has real test files shouldn't get a
    # gratuitous README dropped in -- only an EMPTY tests/ gets the one-liner.
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_existing.py").write_text("# real test\n", encoding="utf-8")

    init_bundle(tmp_path)

    assert not (tmp_path / "tests" / "README.md").exists()


def test_pull_writes_lib_readme_when_scaffolding(
    bundle_dir: Path, cli, fake_backend, toml_writer
) -> None:
    # bundle_dir already has automations/tests/.hassle but no lib/ dir at all
    # (it's a hand-rolled fixture, not `hassle init`'s own output) -- pull must
    # scaffold lib/ (and its README) the same way init does.
    _backend, token = fake_backend
    toml_writer(bundle_dir, backend_token=token)
    assert not (bundle_dir / "lib").exists()

    result = cli(["pull"], cwd=bundle_dir)
    assert result.exit_code == 0, result.output

    readme = bundle_dir / "lib" / "README.md"
    assert readme.is_file()
    assert "@macro" in readme.read_text(encoding="utf-8")
