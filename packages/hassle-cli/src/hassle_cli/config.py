"""`hassle.toml` -- the per-bundle config file (DESIGN §8.4, MILESTONES M7).

Minimal, hand-rollable TOML subset (this project only ever needs flat
key = "value"/true/false/integer pairs, so a tiny parser avoids adding a
`tomli`/`tomllib` version-gate dependency -- Python 3.12 ships `tomllib` for
reads, used here; writes are simple enough to hand-format).

Fields:
- `ha_url` -- the HA base URL (or a `fake://<token>` test seam, never written
  by production code).
- `format_version` -- bundle format version (M9 will use this for the
  upgrade-error check; M7 just writes/reads it).
- `mirror` -- DESIGN §8.5, off by default.
- `token` -- **never legitimately present**; if found, `pull`/`doctor` treat
  it as a committed-secret error (DESIGN §14, MILESTONES M7 test 6).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

CONFIG_FILENAME = "hassle.toml"


@dataclass
class BundleConfig:
    ha_url: str | None = None
    format_version: int = 1
    mirror: bool = False
    token: str | None = None  # only ever set if someone committed one (a bug)

    @property
    def has_committed_token(self) -> bool:
        return bool(self.token)


def find_bundle_root(start: Path | None = None) -> Path | None:
    """Walk up from `start` (or cwd) looking for `hassle.toml`."""
    here = (start or Path.cwd()).resolve()
    for directory in (here, *here.parents):
        if (directory / CONFIG_FILENAME).is_file():
            return directory
    return None


def load_config(bundle_root: Path) -> BundleConfig:
    path = bundle_root / CONFIG_FILENAME
    if not path.is_file():
        return BundleConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return BundleConfig(
        ha_url=data.get("ha_url"),
        format_version=int(data.get("format_version", 1)),
        mirror=bool(data.get("mirror", False)),
        token=data.get("token"),
    )


def write_default_config(bundle_root: Path, *, ha_url: str | None = None) -> None:
    """Write a fresh `hassle.toml` (used by `hassle init`)."""
    path = bundle_root / CONFIG_FILENAME
    lines = [
        f'ha_url = "{ha_url}"' if ha_url else '# ha_url = "http://homeassistant.local:8123"',
        "format_version = 1",
        "mirror = false",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
