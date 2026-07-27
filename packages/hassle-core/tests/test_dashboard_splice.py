"""Dashboard splice identity resolution (docs/internals/dashboards-design.md
§6.2): ``_DEF_DECORATOR_KINDS`` recognizes ``@dashboard``/``@raw_dashboard``,
and their identity is the ``url_path=``/``default=True`` kwarg -- never
``id=`` (dashboards have no ``id=`` kwarg at all, §3.1) -- so a refresh
targets the SINGLE decorated def whose declared identity matches, exactly
like automations/scripts, rather than falling back to name-matching.
"""

from __future__ import annotations

from pathlib import Path

from hassle.decompiler.splice import find_object_statement_name, splice_object

TWO_DASHBOARDS = """from hassle import *
from hassle.registry import entities as e


@dashboard(url_path="climate-control", title="Climate")
def climate_control():
    with view():
        with section():
            raw_card({"type": "tile", "entity": "climate.living_room"})


@raw_dashboard(url_path="energy-media")
def energy_media():
    return {
        "meta": {"url_path": "energy-media", "title": "Energy"},
        "config": {"views": []},
    }
"""

REPLACEMENT = """@dashboard(url_path="climate-control", title="Climate Control (UI edit)")
def climate_control():
    with view():
        pass
"""


def _write(tmp_path: Path, source: str = TWO_DASHBOARDS) -> Path:
    path = tmp_path / "dashboards.py"
    path.write_text(source, encoding="utf-8")
    return path


def test_find_object_statement_name_resolves_dashboard_by_url_path(tmp_path: Path) -> None:
    target = _write(tmp_path)
    assert find_object_statement_name(target.read_text(), "dashboard:climate-control") == (
        "climate_control"
    )
    assert (
        find_object_statement_name(target.read_text(), "dashboard:energy-media") == "energy_media"
    )


def test_find_object_statement_name_resolves_default_dashboard_sentinel(tmp_path: Path) -> None:
    source = (
        "from hassle import *\n\n\n"
        "@dashboard(default=True)\n"
        "def home():\n"
        "    with view():\n"
        "        pass\n"
    )
    target = _write(tmp_path, source)
    assert find_object_statement_name(target.read_text(), "dashboard:default") == "home"


def test_splice_targets_by_url_path_not_def_name(tmp_path: Path) -> None:
    # The def name need not equal the url_path -- identity is the
    # `url_path=`/`default=True` kwarg, mirroring the `id=` convention for
    # automations/scripts.
    source = TWO_DASHBOARDS.replace("def climate_control():", "def climate():")
    target = _write(tmp_path, source)

    new_source = splice_object(
        target.read_text(),
        object_key="dashboard:climate-control",
        new_source=REPLACEMENT,
        updated_on="2026-07-27",
    )

    assert "def climate():" not in new_source
    assert "Climate Control (UI edit)" in new_source
    assert "def energy_media():" in new_source  # sibling untouched
    assert '"url_path": "energy-media"' in new_source


def test_splice_never_matches_the_other_dashboard(tmp_path: Path) -> None:
    target = _write(tmp_path)
    new_source = splice_object(
        target.read_text(),
        object_key="dashboard:climate-control",
        new_source=REPLACEMENT,
        updated_on="2026-07-27",
    )
    assert "def energy_media():" in new_source
    assert '"title": "Energy"' in new_source


def test_splice_raw_dashboard_by_url_path(tmp_path: Path) -> None:
    target = _write(tmp_path)
    raw_replacement = (
        '@raw_dashboard(url_path="energy-media")\n'
        "def energy_media():\n"
        '    return {"meta": {"url_path": "energy-media", "title": "Energy (UI edit)"}, '
        '"config": {"views": []}}\n'
    )
    new_source = splice_object(
        target.read_text(),
        object_key="dashboard:energy-media",
        new_source=raw_replacement,
        updated_on="2026-07-27",
    )
    assert "Energy (UI edit)" in new_source
    assert "def climate_control():" in new_source  # sibling untouched
