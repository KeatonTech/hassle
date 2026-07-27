"""Corpus loader shared by the IR round-trip tests.

Maps each `fixtures/configs/*.json` file to its object *kind* using the
filename convention the corpus is built to:

    automation_*.json        -> kind "automation"      (id lives in the body)
    script_*.json            -> kind "script"          (object_id = filename stem)
    helper_<domain>_*.json   -> kind "<domain>"        (id lives in the body)
    dashboard_*.json         -> kind "dashboard"       (identity lives in `meta.url_path`,
                                                         or the "default" sentinel)

`.provenance.md` sidecars are ignored.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

HELPER_DOMAINS: frozenset[str] = frozenset(
    {
        "input_boolean",
        "input_number",
        "input_select",
        "input_text",
        "input_datetime",
        "input_button",
        "counter",
        "timer",
        "schedule",
    }
)


def repo_root() -> Path:
    # _corpus.py -> tests -> hassle-core -> packages -> repo root
    return Path(__file__).resolve().parents[3]


def configs_dir() -> Path:
    return repo_root() / "fixtures" / "configs"


@dataclass(frozen=True)
class Fixture:
    name: str
    kind: str
    key_hint: str | None
    config: dict[str, Any]
    path: Path


def _kind_for(name: str) -> tuple[str, str | None]:
    if name.startswith("automation"):
        return "automation", None
    if name.startswith("script"):
        # Scripts are keyed by object_id, which is extrinsic to the config body;
        # the filename stem stands in as the object_id for corpus round-tripping.
        return "script", name
    if name.startswith("dashboard"):
        # A dashboard's identity lives in `meta.url_path` (or falls to the
        # "default" sentinel for the default dashboard, §3.1) -- never
        # extrinsic to the body, so no key_hint is needed (unlike scripts).
        return "dashboard", None
    if name.startswith("helper_"):
        rest = name[len("helper_") :]
        for dom in sorted(HELPER_DOMAINS, key=len, reverse=True):
            if rest == dom or rest.startswith(dom + "_"):
                return dom, None
        raise ValueError(f"cannot determine helper domain from fixture name {name!r}")
    raise ValueError(f"cannot determine object kind from fixture name {name!r}")


def load_corpus() -> list[Fixture]:
    directory = configs_dir()
    fixtures: list[Fixture] = []
    if not directory.is_dir():
        return fixtures
    for path in sorted(directory.glob("*.json")):
        name = path.stem
        kind, key_hint = _kind_for(name)
        config = json.loads(path.read_text(encoding="utf-8"))
        fixtures.append(Fixture(name, kind, key_hint, config, path))
    return fixtures
