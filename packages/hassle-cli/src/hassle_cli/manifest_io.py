"""`manifest.lock` read/write (DESIGN §8.1).

`Manifest.canonical_json()` (hassle-core) gives stable serialization; this
module just owns the file path convention (`.hassle/manifest.lock`, committed
to git per DESIGN §8.1) and default-empty-manifest construction. `synced_at`
is always caller-supplied (no wall clock in core logic, docs/backend.md) --
the CLI is the only layer allowed to call a clock, so `now_iso()` lives here,
not in hassle-core.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from hassle.sync import Manifest

MANIFEST_RELATIVE_PATH = Path(".hassle") / "manifest.lock"


def manifest_path(bundle_root: Path) -> Path:
    return bundle_root / MANIFEST_RELATIVE_PATH


def load_manifest(bundle_root: Path) -> Manifest:
    path = manifest_path(bundle_root)
    if not path.is_file():
        return Manifest(synced_at="", ha_version="", objects={})
    data = json.loads(path.read_text(encoding="utf-8"))
    return Manifest.model_validate(data)


def save_manifest(bundle_root: Path, manifest: Manifest) -> None:
    path = manifest_path(bundle_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(manifest.canonical_json() + "\n", encoding="utf-8")


def now_iso() -> str:
    """The only wall-clock call in the CLI layer (core logic never calls
    this; `synced_at` is always supplied by the caller)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
