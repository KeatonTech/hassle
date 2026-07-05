"""HA version-range check (DESIGN §4, §15; MILESTONES M6).

`DirectBackend` reads the instance's HA version from `get_config` and warns when
it falls outside the range Hassle has been tested against — CI exercises the
integration suite on HA `stable` and `dev` (MILESTONES M6 "Done when"), and this
is the range those correspond to. The check is deliberately a *warning*, never a
hard failure: Hassle should still function against an untested HA, it just can't
promise it (DESIGN §15's "CLI checks HA version via get_config and warns outside
the tested range").

Kept as pure logic (no I/O) so it is unit-testable without a live instance.
"""

from __future__ import annotations

import re

# The tested range. Lower bound: HA 2024.10, where the plural-schema storage
# normalization (docs/ha-api-notes.md §10.1) landed — the earliest HA whose
# stored form matches Hassle's canonical form. Upper bound: a little above the
# current `dev` line, refreshed as CI's `stable`/`dev` tags advance.
TESTED_HA_MIN = "2024.10.0"
TESTED_HA_MAX = "2026.12.99"

_VERSION_RE = re.compile(r"^\s*(\d+)\.(\d+)(?:\.(\d+))?")


def parse_ha_version(version: str) -> tuple[int, int, int] | None:
    """Parse a calendar version ``YYYY.M[.P]`` into a comparable tuple.

    Tolerant of trailing pre-release suffixes (``2026.7.0b3`` -> ``(2026, 7, 0)``)
    since only the numeric ordering matters here. Returns ``None`` if the string
    has no leading ``YYYY.M`` at all.
    """
    match = _VERSION_RE.match(version)
    if match is None:
        return None
    year, month, patch = match.group(1), match.group(2), match.group(3)
    return (int(year), int(month), int(patch) if patch is not None else 0)


def version_warning(version: str) -> str | None:
    """Return a one-paragraph warning if ``version`` is outside the tested range.

    ``None`` when in range. An unparseable version yields a warning (never a
    crash) so the CLI degrades gracefully.
    """
    parsed = parse_ha_version(version)
    if parsed is None:
        return (
            f"Could not parse the Home Assistant version {version!r} reported by "
            "GET /api/config. Fix: Hassle is tested against HA "
            f"{TESTED_HA_MIN}-{TESTED_HA_MAX}; if this is a real HA build, please "
            "report the version string so the range can be updated."
        )
    low = parse_ha_version(TESTED_HA_MIN)
    high = parse_ha_version(TESTED_HA_MAX)
    assert low is not None and high is not None  # module constants are valid
    if parsed < low or parsed > high:
        return (
            f"Home Assistant {version} is outside the range Hassle has been "
            f"tested against ({TESTED_HA_MIN}-{TESTED_HA_MAX}). Fix: Hassle should "
            "still work, but sync/round-trip behavior is only guaranteed inside "
            "the tested range — upgrade Hassle or pin HA within it if you hit "
            "storage-schema surprises."
        )
    return None
