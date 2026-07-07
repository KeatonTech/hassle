"""`hassle.toml` -- the per-bundle config file (DESIGN §8.4, MILESTONES M7).

Minimal, hand-rollable TOML subset (this project only ever needs flat
key = "value"/true/false/integer pairs plus one string array, so a tiny parser
avoids adding a `tomli`/`tomllib` version-gate dependency -- Python 3.12 ships
`tomllib` for reads, used here; writes are simple enough to hand-format).

Fields:
- `ha_url` -- the HA base URL (or a `fake://<token>` test seam, never written
  by production code).
- `bundle_format` -- the bundle format version (MILESTONES M9 test 4: the CLI
  refuses to operate on a bundle whose major version is NEWER than what this
  CLI build understands, with a clear upgrade error). Renamed from the M7
  placeholder field `format_version` (M9); `load_config` still reads the old
  key name too (see `load_config`'s docstring) so a bundle written by an
  older `hassle init` keeps working with no migration step.
- `mirror` -- DESIGN §8.5, off by default.
- `token` -- **never legitimately present**; if found, `pull`/`doctor` treat
  it as a committed-secret error (DESIGN §14, MILESTONES M7 test 6).
- `ignore` -- DESIGN §8.2/§6 amendment (owner decision, `ux/pull-organization`):
  a list of `fnmatch` globs on object keys (e.g. `"input_boolean:material_you_*"`)
  that Hassle must never adopt, refresh, or delete -- see `hassle_cli.ignore_filter`
  for the filtering semantics. Defaults to empty (today's "nothing is ever
  unmanaged" behavior is unchanged unless the user opts in).
- `toolchain_path` -- MILESTONES M17: an explicit path to a Hassle source
  checkout (the directory containing `packages/`), used by
  `hassle_cli.uv_project.resolve_toolchain_path` as the HIGHEST-priority entry
  in the bundle-as-uv-project `[tool.uv.sources]` resolution order (beats
  auto-detection). `None` (absent) is the common case -- auto-detection or the
  bare-dependency fallback are used instead; see that module's docstring for
  the full order.

MILESTONES M15 work item B bumps `CURRENT_BUNDLE_FORMAT` to 2 (the
category-first, root-level bundle layout -- the RETIRED per-kind trees
`automations/`/`scripts/`/`helpers/` are a breaking layout change an OLDER
CLI build cannot make sense of, the exact M9-test-4 "older CLI, newer bundle"
shape). Unlike a hand-authored `hassle.toml` bump, format `2` is written by
`hassle pull` ITSELF (`bump_bundle_format`) the moment it finishes migrating
an old-layout bundle -- never by `hassle init` retroactively rewriting an
existing bundle's file, and never required before migration can run (a
format-`1` bundle is exactly what triggers migration in the first place).
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

CONFIG_FILENAME = "hassle.toml"

#: The bundle format version THIS CLI build understands (MILESTONES M9 test 4).
#: A bundle whose `bundle_format` is newer (a greater integer -- there is only
#: ever one "major" component, matching how `format_version`/`bundle_format`
#: has always been stored, a single int) refuses to run with a clear upgrade
#: error rather than attempting a partial operation.
#:
#: MILESTONES M15 work item B: bumped 1 -> 2 for the category-first,
#: root-level layout (the RETIRED `automations/`/`scripts/`/`helpers/` trees).
#: A format-1 bundle is NOT refused (only NEWER-than-understood is, per M9
#: test 4's "older CLI accepts older/equal" rule) -- `hassle pull` migrates it
#: in place and writes `bundle_format = 2` itself once migration completes.
CURRENT_BUNDLE_FORMAT = 2


@dataclass
class BundleConfig:
    ha_url: str | None = None
    bundle_format: int = 1
    mirror: bool = False
    token: str | None = None  # only ever set if someone committed one (a bug)
    ignore: list[str] = field(default_factory=list)
    toolchain_path: str | None = None

    @property
    def has_committed_token(self) -> bool:
        return bool(self.token)

    @property
    def format_version(self) -> int:
        """Deprecated alias for `bundle_format` (the M7-era field name)."""
        return self.bundle_format


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
    # `bundle_format` is the current key; `format_version` (M7-era) is still
    # accepted for a bundle whose hassle.toml predates the M9 rename -- no
    # migration step required. `bundle_format` wins if a bundle somehow has
    # both (shouldn't happen in practice, but pick a deterministic winner).
    raw_format = data.get("bundle_format", data.get("format_version", 1))
    return BundleConfig(
        ha_url=data.get("ha_url"),
        bundle_format=int(raw_format),
        mirror=bool(data.get("mirror", False)),
        token=data.get("token"),
        ignore=list(data.get("ignore", [])),
        toolchain_path=data.get("toolchain_path"),
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


def persist_toolchain_path(bundle_root: Path, toolchain_path: str) -> None:
    """Write/replace `toolchain_path` in the bundle's `hassle.toml`, creating
    the file if missing (MILESTONES M17). Line-surgical, same convention as
    `persist_ha_url`: every other line is preserved byte-for-byte."""
    toml_path = bundle_root / CONFIG_FILENAME
    new_line = f'toolchain_path = "{toolchain_path}"'
    if not toml_path.is_file():
        toml_path.write_text(new_line + "\n", encoding="utf-8")
        return
    lines = toml_path.read_text(encoding="utf-8").splitlines()
    live = re.compile(r"^\s*toolchain_path\s*=")
    for i, line in enumerate(lines):
        if live.match(line):
            lines[i] = new_line
            break
    else:
        lines.append(new_line)
    toml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def bump_bundle_format(bundle_root: Path, *, to: int = CURRENT_BUNDLE_FORMAT) -> None:
    """Write/replace `bundle_format` in the bundle's `hassle.toml` (MILESTONES
    M15 work item B: `hassle pull` calls this itself once it finishes
    migrating an old-layout bundle to the new one -- never a hand-authored
    step). Line-surgical, same convention as `persist_ha_url`: every other
    line is preserved byte-for-byte. Also replaces a legacy `format_version =`
    line in place (rather than leaving a stale key alongside a new one) since
    `load_config` prefers `bundle_format` but a leftover `format_version` line
    would be confusing to a human reading the file afterward."""
    toml_path = bundle_root / CONFIG_FILENAME
    new_line = f"bundle_format = {to}"
    if not toml_path.is_file():
        toml_path.write_text(new_line + "\n", encoding="utf-8")
        return
    lines = toml_path.read_text(encoding="utf-8").splitlines()
    bundle_format_re = re.compile(r"^\s*bundle_format\s*=")
    format_version_re = re.compile(r"^\s*format_version\s*=")
    for i, line in enumerate(lines):
        if bundle_format_re.match(line):
            lines[i] = new_line
            break
    else:
        for i, line in enumerate(lines):
            if format_version_re.match(line):
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
        f"bundle_format = {CURRENT_BUNDLE_FORMAT}",
        "mirror = false",
        "# ignore = []  # fnmatch globs on object keys Hassle must never touch,",
        '#              # e.g. ["input_boolean:material_you_*"]',
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
