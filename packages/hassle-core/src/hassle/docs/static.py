"""Loader for the packaged static copies of `docs/DSL.md`/`docs/COOKBOOK.md`
(MILESTONES M9: `hassle init`/`hassle pull` write these into every user
bundle). The installed `hassle` package doesn't carry the repo's
`fixtures/`, so these are pre-rendered, checked-in copies under
`hassle/docs/_static/` -- refreshed only via `hassle-dev docs --update`
(R3: same golden-file discipline as `expected_ir.json`), never hand-edited.
"""

from __future__ import annotations

from importlib import resources


def load_dsl_md() -> str:
    return resources.files("hassle.docs._static").joinpath("DSL.md").read_text(encoding="utf-8")


def load_cookbook_md() -> str:
    return (
        resources.files("hassle.docs._static").joinpath("COOKBOOK.md").read_text(encoding="utf-8")
    )
