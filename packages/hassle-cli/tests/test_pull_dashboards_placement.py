"""Dashboard placement + pull-routing tests (docs/internals/dashboards-design.md
§7): `default_source_path`'s dashboard branch (module-safe naming,
`_SCOPE_FOR_KIND`'s deliberate omission, `category_shaped_stem`'s
"uncategorized" treatment of `dashboards/x.py`), the on-demand `dashboards/`
directory scaffold (no `__init__.py`), and the adopt-append safety net that
keeps ADOPT from clobbering an existing file at a dashboard's default path.

**Hard dependency boundary**: `decompile_object` support for
:class:`~hassle.ir.models.DashboardConfig` is workstream DB4's scope and
hasn't landed on this branch yet, so nothing here can drive
`hassle.sync.pull_apply.apply_pull_with_decompiler` for a dashboard object --
`decompile_bundle` has no dispatch branch for the kind yet. Every test below
instead drives the STUB pull engine (`hassle.sync.pull.apply_pull` +
`_placeholder_dsl_source`) with `RecordingSourceWriter`/real tmp-dir writers,
which is enough to pin the PLACEMENT and ROUTING contract (which file,
whole-file write vs. splice/append) independent of decompiled content. DB4
should extend this file with real decompiler-backed adopt/refresh/splice
cases once `decompile_object` supports `DashboardConfig`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from hassle.ir.keys import DASHBOARD_KIND, category_shaped_stem
from hassle.registry.snapshot import RegistrySnapshot
from hassle.sync.category_writeback import (
    _SCOPE_FOR_KIND,  # pyright: ignore[reportPrivateUsage]
)
from hassle.sync.models import Plan, PlanAction, PlanEntry
from hassle.sync.pull import apply_pull
from hassle.sync.source_writer import RecordingSourceWriter, SplicingSourceWriter
from hassle_cli.bundle_ops import default_source_path

# ---------------------------------------------------------------------------
# Placement: default_source_path's dashboard branch
# ---------------------------------------------------------------------------


def test_default_source_path_for_named_dashboard() -> None:
    assert default_source_path("dashboard:climate-control") == "dashboards/climate_control.py"


def test_default_source_path_for_default_dashboard_sentinel() -> None:
    assert default_source_path("dashboard:default") == "dashboards/default.py"


def test_default_source_path_hyphen_becomes_underscore() -> None:
    assert default_source_path("dashboard:guest-mode-panel") == "dashboards/guest_mode_panel.py"


def test_default_source_path_leading_digit_gets_underscore_prefix() -> None:
    # Mirrors the stub generator's leading-digit rule
    # (`hassle.registry.stubs._attr_name`): a leading digit gets a single
    # underscore prefix, since a Python module name can't start with one.
    assert default_source_path("dashboard:3d-printer-view") == "dashboards/_3d_printer_view.py"


def test_default_source_path_ignores_registry_for_dashboards() -> None:
    # Dashboards have no category-registry scope at all (`_SCOPE_FOR_KIND`
    # has no entry for the kind -- pinned below) -- passing a registry must
    # never redirect a dashboard's placement to a category file or `misc.py`.
    snapshot = RegistrySnapshot()
    assert (
        default_source_path("dashboard:climate-control", registry=snapshot)
        == "dashboards/climate_control.py"
    )


def test_scope_for_kind_has_no_dashboard_entry() -> None:
    # DESIGN §7: dashboards have no category-registry scope to write back to
    # (HA has no `lovelace` category scope) -- `_SCOPE_FOR_KIND` deliberately
    # gets no entry for the kind. `_category_source_path`/
    # `category_display_names_for_paths` both short-circuit via this map, so
    # this single assertion is the whole no-category-writeback contract.
    assert DASHBOARD_KIND not in _SCOPE_FOR_KIND


def test_category_shaped_stem_treats_dashboards_path_as_uncategorized() -> None:
    # `dashboards/x.py` is a NESTED path with no `__init__.py`-marked package
    # root (pull never creates one -- see the scaffolding tests below), so it
    # is never category-shaped (docs/internals/dashboards-design.md §7):
    # pinned here, `category_shaped_stem`'s logic is unchanged.
    assert category_shaped_stem("dashboards/climate_control.py") is None
    assert category_shaped_stem("dashboards/climate_control.py", package_roots=frozenset()) is None
    # It's the ABSENCE of "dashboards" from `package_roots` that keeps this
    # uncategorized -- not a dashboard-specific carve-out in the predicate.
    # If a user deliberately opted a `dashboards/` directory into a category
    # PACKAGE (added their own `__init__.py`), the existing, kind-independent
    # rule would apply exactly like any other package.
    assert (
        category_shaped_stem(
            "dashboards/climate_control.py", package_roots=frozenset({"dashboards"})
        )
        == "dashboards"
    )


# ---------------------------------------------------------------------------
# Scaffolding: dashboards/ created on demand, without __init__.py
# ---------------------------------------------------------------------------


def _adopt_entry(object_key: str, source_path: str, remote: dict[str, object]) -> PlanEntry:
    return PlanEntry(
        object_key=object_key,
        kind=DASHBOARD_KIND,
        action=PlanAction.ADOPT,
        remote=remote,
        source_path=source_path,
    )


_CLIMATE_ENVELOPE = {
    "meta": {"url_path": "climate-control", "title": "Climate"},
    "config": {"views": []},
}


def test_adopt_scaffolds_dashboards_directory_without_init_py(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    plan = Plan(
        entries=[
            _adopt_entry(
                "dashboard:climate-control", "dashboards/climate_control.py", _CLIMATE_ENVELOPE
            )
        ]
    )
    writer = SplicingSourceWriter(updated_on="2026-07-27")
    apply_pull(plan, writer)

    dashboards_dir = tmp_path / "dashboards"
    assert dashboards_dir.is_dir()
    assert (dashboards_dir / "climate_control.py").is_file()
    assert not (dashboards_dir / "__init__.py").exists()
    assert sorted(p.name for p in dashboards_dir.iterdir()) == ["climate_control.py"]


def test_adopt_scaffolds_dashboards_directory_with_recording_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Same scaffold check with the in-memory test double: `RecordingSourceWriter`
    # never touches disk, so the ONLY directory-creation authority under test
    # here is `WholeFileSourceWriter`/`SplicingSourceWriter`'s own
    # `path.parent.mkdir(parents=True, exist_ok=True)` -- this test instead
    # pins that the routing call itself names the right, un-prefixed path
    # (no directory is implicitly widened into a package).
    monkeypatch.chdir(tmp_path)
    plan = Plan(
        entries=[
            _adopt_entry(
                "dashboard:climate-control", "dashboards/climate_control.py", _CLIMATE_ENVELOPE
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert list(writer.written_files) == [Path("dashboards/climate_control.py")]


# ---------------------------------------------------------------------------
# Adopt-append safety: never write_whole_file over an existing path
# ---------------------------------------------------------------------------


def test_adopt_routes_through_splice_when_default_path_already_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A brand-new adopted dashboard's default target path already has real
    content on disk (a hand-authored file, or two identities collapsing onto
    the same module-safe stem -- docs/internals/dashboards-design.md §7).
    ADOPT must route through the splice/append path -- `RecordingSourceWriter`
    exposes this as `spliced_objects`, never `written_files`."""
    monkeypatch.chdir(tmp_path)
    dashboards_dir = tmp_path / "dashboards"
    dashboards_dir.mkdir()
    existing_path = dashboards_dir / "climate_control.py"
    existing_path.write_text("# hand-authored, keep me\n", encoding="utf-8")

    plan = Plan(
        entries=[
            _adopt_entry(
                "dashboard:climate-control", "dashboards/climate_control.py", _CLIMATE_ENVELOPE
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)

    assert writer.written_files == {}
    assert len(writer.spliced_objects) == 1
    path, object_key, _content = writer.spliced_objects[0]
    assert path == Path("dashboards/climate_control.py")
    assert object_key == "dashboard:climate-control"


def test_adopt_of_brand_new_path_still_writes_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The common case is unaffected: nothing pre-exists at the target path,
    # so ADOPT still creates it directly via write_whole_file.
    monkeypatch.chdir(tmp_path)
    plan = Plan(
        entries=[
            _adopt_entry(
                "dashboard:climate-control", "dashboards/climate_control.py", _CLIMATE_ENVELOPE
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert writer.spliced_objects == []
    assert list(writer.written_files.keys()) == [Path("dashboards/climate_control.py")]


def test_splicing_writer_append_path_is_kind_agnostic_for_dashboards(tmp_path: Path) -> None:
    """Low-level proof that `SplicingSourceWriter`'s existing append-under-
    marker behavior (already proven for `automation` in
    `test_pull_adopt_preserves_existing_file.py::
    test_apply_pull_adopt_splices_into_existing_file`) needs no
    dashboard-specific code at all: it only cares that the object statement
    isn't found in the existing file, never about the object's kind.

    Uses hand-written, syntactically-valid DSL source standing in for what
    DB4's decompiler will eventually produce -- this repo has no typed
    dashboard DSL yet (workstreams DB2/DB3), so `@raw_dashboard` here is
    never imported/compiled, only spliced as text; `_DEF_DECORATOR_KINDS`
    (docs/internals/dashboards-design.md §6.2) doesn't recognize it as a
    `dashboard` declaration yet either (DB4's job), so `find_object_statement_
    name` falls through to "not found here" regardless -- which is exactly
    the correct determination for a brand-new adopt into a file that has
    never defined this object, so the append path fires for the right
    reason even ahead of DB4.
    """
    existing_source = "# hand-authored, keep me\nCONSTANT = 42\n"
    path = tmp_path / "dashboards" / "climate_control.py"
    path.parent.mkdir(parents=True)
    path.write_text(existing_source, encoding="utf-8")

    new_object_source = (
        "from hassle import raw_dashboard\n\n\n"
        '@raw_dashboard(url_path="climate-control")\n'
        "def climate_control():\n"
        '    return {"meta": {"url_path": "climate-control"}, "config": {"views": []}}\n'
    )
    writer = SplicingSourceWriter(updated_on="2026-07-27")
    writer.splice_object(path, "dashboard:climate-control", new_object_source)

    written = path.read_text(encoding="utf-8")
    assert "hand-authored, keep me" in written
    assert "CONSTANT = 42" in written
    assert "def climate_control" in written
    assert "climate-control" in written
