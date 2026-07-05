"""`hassle doctor`: committed-secret scan + orphaned shadow-automation sweep
(DESIGN §10.4 point 4; DESIGN §14; MILESTONES M7 test 6).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from hassle_cli.run_live import SHADOW_ID_PREFIX

# A long-lived HA token is a long base64url-ish string; HA's own tokens are JWTs
# (three dot-separated base64url segments) but users sometimes paste other
# long opaque strings too, so this also flags anything assigned to a
# `token = "..."` TOML key regardless of shape -- the *key name* is the signal,
# not the value's exact format (a `hassle.toml` should never legitimately have
# a `token` key at all, per DESIGN §14).
_TOKEN_KEY_RE = re.compile(r'^\s*token\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


def find_committed_tokens(bundle_root: Path) -> list[tuple[Path, str]]:
    """Scan `hassle.toml` (and any other top-level `.toml`) for a `token =`
    key. Returns `(path, matched_value)` pairs."""
    found: list[tuple[Path, str]] = []
    for path in bundle_root.glob("*.toml"):
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in _TOKEN_KEY_RE.finditer(text):
            found.append((path, match.group(1)))
    return found


def sweep_orphaned_shadows(backend: Any) -> list[str]:
    """Delete every `hassle_shadow_*` automation currently in `backend`
    (DESIGN §10.4: "hassle doctor sweeps orphans"). Returns the identities
    removed."""
    swept: list[str] = []
    for identity in list(backend.list_remote("automation")):
        if identity.startswith(SHADOW_ID_PREFIX):
            backend.delete("automation", identity)
            swept.append(identity)
    return swept
