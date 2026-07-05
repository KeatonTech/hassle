"""`hassle.toml` -- the per-bundle config file (DESIGN §8.4, MILESTONES M7).

Minimal, hand-rollable TOML subset (this project only ever needs flat
key = "value"/true/false/integer pairs plus one string array, so a tiny parser
avoids adding a `tomli`/`tomllib` version-gate dependency -- Python 3.12 ships
`tomllib` for reads, used here; writes are simple enough to hand-format).

Fields:
- `ha_url` -- the HA base URL (or a `fake://<token>` test seam, never written
  by production code).
- `format_version` -- bundle format version (M9 will use this for the
  upgrade-error check; M7 just writes/reads it).
- `mirror` -- DESIGN §8.5, off by default.
- `token` -- **never legitimately present**; if found, `pull`/`doctor` treat
  it as a committed-secret error (DESIGN §14, MILESTONES M7 test 6).
- `ignore` -- DESIGN §8.2/§6 amendment (owner decision, `ux/pull-organization`):
  a list of `fnmatch` globs on object keys (e.g. `"input_boolean:material_you_*"`)
  that Hassle must never adopt, refresh, or delete -- see `hassle_cli.ignore_filter`
  for the filtering semantics. Defaults to empty (today's "nothing is ever
  unmanaged" behavior is unchanged unless the user opts in).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "hassle.toml"


@dataclass
class BundleConfig:
    ha_url: str | None = None
    format_version: int = 1
    mirror: bool = False
    token: str | None = None  # only ever set if someone committed one (a bug)
    ignore: list[str] = field(default_factory=list)

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
        ignore=list(data.get("ignore", [])),
    )


def persist_ha_url(bundle_root: Path, ha_url: str) -> None:
    """Write/replace `ha_url` in the bundle's hassle.toml, creating the file if
    missing. Line-surgical on purpose: every other line (comments, user
    settings) is preserved byte-for-byte. The token is NEVER written here --
    it lives in the keyring (DESIGN §14)."""
    toml_path = bundle_root / "hassle.toml"
    new_line = f'ha_url = "{ha_url}"'
    if not toml_path.is_file():
        toml_path.write_text(new_line + "\n", encoding="utf-8")
        return
    lines = toml_path.read_text(encoding="utf-8").splitlines()
    live = re.compile(r"^\s*ha_url\s*=")
    placeholder = re.compile(r"^\s*#\s*ha_url\s*=")
    for i, line in enumerate(lines):
        if live.match(line):
            lines[i] = new_line
            break
    else:
        for i, line in enumerate(lines):
            if placeholder.match(line):
                lines[i] = new_line
                break
        else:
            lines.append(new_line)
    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_default_config(bundle_root: Path, *, ha_url: str | None = None) -> None:
    """Write a fresh `hassle.toml` (used by `hassle init`)."""
    path = bundle_root / CONFIG_FILENAME
    lines = [
        f'ha_url = "{ha_url}"' if ha_url else '# ha_url = "http://homeassistant.local:8123"',
        "format_version = 1",
        "mirror = false",
        "# ignore = []  # fnmatch globs on object keys Hassle must never touch,",
        '#              # e.g. ["input_boolean:material_you_*"]',
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
