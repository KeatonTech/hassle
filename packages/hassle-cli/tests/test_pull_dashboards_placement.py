"""Dashboard placement + pull-routing tests (docs/internals/dashboards-design.md
§7): `default_source_path`'s dashboard branch (module-safe naming, sanitized
against path traversal; `_SCOPE_FOR_KIND`'s deliberate omission;
`category_shaped_stem`'s "uncategorized" treatment of `dashboards/x.py`), the
on-demand `dashboards/` directory scaffold (no `__init__.py`), and the
adopt-append safety net that keeps ADOPT from clobbering an existing file at
a dashboard's default path.

**Hard dependency boundary**: `decompile_object` support for
:class:`~hassle.ir.models.DashboardConfig` is workstream DB4's scope and
hasn't landed on this branch yet, so nothing here can drive
`hassle.sync.pull_apply.apply_pull_with_decompiler` for a dashboard object --
`decompile_bundle` has no dispatch branch for the kind yet. Every test below
instead drives the STUB pull engine (`hassle.sync.pull.apply_pull` +
`_placeholder_dsl_source`) with `RecordingSourceWriter`/real tmp-dir writers,
which is enough to pin the PLACEMENT and ROUTING contract (which file,
whole-file write vs. byte-preserving append) independent of decompiled
content. DB4 should extend this file with real decompiler-backed
adopt/refresh/splice cases once `decompile_object` supports `DashboardConfig`.

**Explicit DB4 handoff item**: `hassle.backend.fake.FakeBackend` now has real
dashboard CRUD support (DB5 landed), so a bundle CAN seed a live dashboard
end-to-end -- but running a real `hassle pull` against a seeded dashboard
still dies inside `hassle.decompiler.decompile_bundle` (no dispatch branch for
`DashboardConfig` yet, DB4's scope). `test_cli_dashboard_kind_smoke.py`'s
plan-level smoke test proves the PLAN side is fine; nothing here or there
attempts an end-to-end `hassle pull` with a seeded dashboard -- DB4 owns that
gap once the decompiler branch lands.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from hassle.ir.keys import DASHBOARD_KIND, category_shaped_stem
from hassle.registry.snapshot import RegistrySnapshot
from hassle.sync.category_writeback import (
    _SCOPE_FOR_KIND,  # pyright: ignore[reportPrivateUsage]
)
from hassle.sync.models import Plan, PlanAction, PlanEntry
from hassle.sync.pull import _placeholder_dsl_source, apply_pull  # pyright: ignore[reportPrivateUsage]
from hassle.sync.source_writer import RecordingSourceWriter, SplicingSourceWriter, WholeFileSourceWriter
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
# Placement safety: identity is never trusted as a bare filename component
# ---------------------------------------------------------------------------
#
# `default_source_path`'s dashboard branch derives a filename from an
# identity that (pre-DB0-verification) is only HYPOTHESIZED to always
# contain a hyphen and nothing else unusual -- the read path (this function)
# must not depend on that hypothesis holding, since it decides where
# `write_whole_file` (mkdir + write, no bundle-root containment check of its
# own) lands on disk.


def test_default_source_path_path_traversal_identity_stays_inside_dashboards_dir() -> None:
    path = default_source_path("dashboard:../../../tmp/pwned-x")
    assert path == "dashboards/tmppwned_x.py"
    assert ".." not in path
    assert path.count("/") == 1  # exactly "dashboards/<name>.py", no nested escape


def test_default_source_path_empty_identity_falls_back_to_safe_name() -> None:
    expected_digest = hashlib.sha256(b"").hexdigest()[:8]
    assert default_source_path("dashboard:") == f"dashboards/dashboard_{expected_digest}.py"


def test_default_source_path_dot_only_identity_falls_back_to_safe_name() -> None:
    expected_digest = hashlib.sha256(b"...").hexdigest()[:8]
    assert default_source_path("dashboard:...") == f"dashboards/dashboard_{expected_digest}.py"


def test_default_source_path_all_underscore_identity_falls_back_to_safe_name() -> None:
    # "---" hyphen->underscore's to "___" -- valid characters, but content-free
    # (an all-underscore module name is legal Python but a useless filename;
    # the safe-fallback rule applies here too, per the sanitizer's contract).
    expected_digest = hashlib.sha256(b"---").hexdigest()[:8]
    assert default_source_path("dashboard:---") == f"dashboards/dashboard_{expected_digest}.py"


def test_default_source_path_normal_url_paths_are_unaffected_by_sanitization() -> None:
    # Sanity: the traversal/empty-identity guards never touch a normal,
    # already-safe url_path.
    assert default_source_path("dashboard:climate-control") == "dashboards/climate_control.py"
    assert default_source_path("dashboard:default") == "dashboards/default.py"
    assert default_source_path("dashboard:3d-printer-view") == "dashboards/_3d_printer_view.py"


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


def _climate_adopt_plan() -> Plan:
    return Plan(
        entries=[
            _adopt_entry(
                "dashboard:climate-control", "dashboards/climate_control.py", _CLIMATE_ENVELOPE
            )
        ]
    )


def test_adopt_scaffolds_dashboards_directory_without_init_py(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    writer = SplicingSourceWriter(updated_on="2026-07-27")
    apply_pull(_climate_adopt_plan(), writer)

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
    writer = RecordingSourceWriter()
    apply_pull(_climate_adopt_plan(), writer)
    assert list(writer.written_files) == [Path("dashboards/climate_control.py")]


# ---------------------------------------------------------------------------
# Adopt-append safety: never lose existing bytes at the default path
# ---------------------------------------------------------------------------
#
# `adopt_write` must preserve pre-existing content BY CONSTRUCTION (read +
# concatenate + one `write_whole_file` call) rather than by delegating to a
# writer's own `splice_object` -- `WholeFileSourceWriter.splice_object` IS
# `write_whole_file` (no preservation at all), and
# `SplicingSourceWriter.splice_object` falls back to a plain
# `write_whole_file` whenever the new content isn't one spliceable statement
# plus imports, which the stub engine's placeholder content (comment-only)
# always is -- so routing ADOPT to `splice_object` was never actually safe
# for it. These tests reproduce the reviewer's exact regression scenario
# (adopting onto a `dashboards/climate_control.py` that already holds
# `# hand-authored, keep me` / `CONSTANT = 42`) against BOTH real writers.

_EXISTING_HAND_AUTHORED = "# hand-authored, keep me\nCONSTANT = 42\n"


def _seed_existing_file(tmp_path: Path) -> Path:
    dashboards_dir = tmp_path / "dashboards"
    dashboards_dir.mkdir()
    existing_path = dashboards_dir / "climate_control.py"
    existing_path.write_text(_EXISTING_HAND_AUTHORED, encoding="utf-8")
    return existing_path


def test_adopt_preserves_existing_file_bytes_with_whole_file_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    existing_path = _seed_existing_file(tmp_path)

    writer = WholeFileSourceWriter()
    apply_pull(_climate_adopt_plan(), writer)

    written = existing_path.read_text(encoding="utf-8")
    assert "# hand-authored, keep me" in written, written
    assert "CONSTANT = 42" in written, written


def test_adopt_preserves_existing_file_bytes_with_splicing_writer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)
    existing_path = _seed_existing_file(tmp_path)

    writer = SplicingSourceWriter(updated_on="2026-07-27")
    apply_pull(_climate_adopt_plan(), writer)

    written = existing_path.read_text(encoding="utf-8")
    assert "# hand-authored, keep me" in written, written
    assert "CONSTANT = 42" in written, written


def test_adopt_still_lands_new_content_after_existing_bytes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Preservation must not come at the cost of the adopt itself: the new
    # object's content still has to land in the file, appended AFTER the
    # pre-existing bytes.
    monkeypatch.chdir(tmp_path)
    existing_path = _seed_existing_file(tmp_path)

    writer = WholeFileSourceWriter()
    apply_pull(_climate_adopt_plan(), writer)

    written = existing_path.read_text(encoding="utf-8")
    assert "dashboard:climate-control" in written, written
    assert written.index("CONSTANT = 42") < written.index("dashboard:climate-control"), written


def test_adopt_of_brand_new_path_still_writes_whole_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The common case is unaffected: nothing pre-exists at the target path,
    # so ADOPT still creates it directly via write_whole_file (a single call,
    # no read-and-merge needed).
    monkeypatch.chdir(tmp_path)
    writer = RecordingSourceWriter()
    apply_pull(_climate_adopt_plan(), writer)
    assert writer.spliced_objects == []
    assert list(writer.written_files.keys()) == [Path("dashboards/climate_control.py")]
    assert writer.written_files[Path("dashboards/climate_control.py")] == _placeholder_dsl_source(
        "dashboard:climate-control", _CLIMATE_ENVELOPE
    )


def test_splicing_writer_append_path_is_kind_agnostic_for_dashboards(tmp_path: Path) -> None:
    """Low-level proof that `SplicingSourceWriter.splice_object`'s existing
    append-under-marker behavior (used by REFRESH, still exercised directly
    here -- `adopt_write` no longer calls `splice_object` at all, see the
    section above) needs no dashboard-specific code: it only cares that the
    object statement isn't found in the existing file, never about the
    object's kind. This test feeds it syntactically-valid content (unlike the
    stub engine's placeholder), which is the case `splice_object` is actually
    designed for.

    Uses hand-written, syntactically-valid DSL source standing in for what
    DB4's decompiler will eventually produce -- this repo has no typed
    dashboard DSL yet (workstreams DB2/DB3), so `@raw_dashboard` here is
    never imported/compiled, only spliced as text.
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


# ---------------------------------------------------------------------------
# Contract completeness: batching and moved-file routing
# ---------------------------------------------------------------------------


def test_n_new_dashboards_adopt_into_n_distinct_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Distinct new dashboards land at distinct default-placement files (no
    # collision) -- N adopts, N files, each written once.
    monkeypatch.chdir(tmp_path)
    slugs = ("climate-control", "security-panel", "guest-mode")
    entries = [
        _adopt_entry(
            f"dashboard:{slug}",
            f"dashboards/{slug.replace('-', '_')}.py",
            {"meta": {"url_path": slug, "title": slug}, "config": {"views": []}},
        )
        for slug in slugs
    ]
    writer = RecordingSourceWriter()
    apply_pull(Plan(entries=entries), writer)
    assert sorted(str(p) for p in writer.written_files) == [
        "dashboards/climate_control.py",
        "dashboards/guest_mode.py",
        "dashboards/security_panel.py",
    ]
    assert writer.spliced_objects == []


def test_refresh_splices_wherever_the_user_moved_the_dashboard() -> None:
    # REFRESH routes to `entry.source_path` verbatim (kind-agnostic,
    # `hassle.sync.pull._refresh`) -- if the manifest records that the user
    # relocated a dashboard's source out of its original default placement
    # (e.g. into a shared `lib/dashboards.py`), refresh targets THAT file,
    # never recomputing a fresh default location. Pinned here for dashboards
    # specifically since §7's per-dashboard-file default makes "the user
    # moved it" a realistic scenario for this kind.
    moved_path = "lib/dashboards.py"
    plan = Plan(
        entries=[
            PlanEntry(
                object_key="dashboard:climate-control",
                kind=DASHBOARD_KIND,
                action=PlanAction.REFRESH,
                remote=_CLIMATE_ENVELOPE,
                source_path=moved_path,
            )
        ]
    )
    writer = RecordingSourceWriter()
    apply_pull(plan, writer)
    assert len(writer.spliced_objects) == 1
    path, object_key, _content = writer.spliced_objects[0]
    assert path == Path(moved_path)
    assert object_key == "dashboard:climate-control"
