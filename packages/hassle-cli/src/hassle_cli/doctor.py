"""`hassle doctor`: committed-secret scan + webhook-ID census + orphaned
shadow-automation sweep (DESIGN §10.4 point 4; DESIGN §14).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING, Any

from hassle_cli.run_live import SHADOW_ID_PREFIX

if TYPE_CHECKING:
    from hassle.sync.plan import ObjectMap

# Directories that are never "the bundle a human might commit": `.git/`
# (VCS internals, not source), `.venv/` (vendored deps -- routinely contain
# JWT-shaped strings in test fixtures with nothing to do with this bundle's
# own HA token), `typings/`/`__pycache__/` (generated), `node_modules/`
# (vendored, for any bundle with a `.vscode`/tooling npm dependency).
_SKIP_DIR_NAMES = frozenset({".git", ".venv", "typings", "__pycache__", "node_modules"})

# Extensions that are essentially never text -- skipped outright rather than
# risking a "successful" UTF-8 decode of binary garbage producing a
# nonsensical match.
_BINARY_SUFFIXES = frozenset(
    {
        ".pyc",
        ".so",
        ".dylib",
        ".dll",
        ".png",
        ".jpg",
        ".jpeg",
        ".gif",
        ".ico",
        ".webp",
        ".woff",
        ".woff2",
        ".ttf",
        ".eot",
        ".zip",
        ".tar",
        ".gz",
        ".whl",
        ".db",
        ".sqlite",
        ".sqlite3",
        ".pdf",
    }
)

# Skip anything bigger than this -- a committed secret is a short line, not
# something hiding in a multi-megabyte file; keeps the scan fast on bundles
# with large generated/data files and avoids wasted work on the rare binary
# file an extension check didn't catch.
_MAX_SCAN_BYTES = 2_000_000

# Key names a long-lived HA token commonly ends up assigned to, across TOML/
# JSON/YAML/`.env`/Python source -- not just `hassle.toml`'s `token` key
# (DESIGN §14: that key should never exist there at all, but a bundle is
# mostly *Python*, and secrets get pasted into all sorts of places and under
# all sorts of names). Matched case-insensitively, so this also covers the
# all-caps `TOKEN`/`HASSLE_TOKEN` env-var convention.
_TOKEN_KEY_NAMES = ("hassle_token", "access_token", "ha_token", "token")

# `<key> (=|:) <value>`, optionally quoted -- covers TOML/Python (`=`), JSON/
# YAML (`:`), and `.env` (`KEY=value`, no quotes). The value must be at least
# 8 non-quote/non-whitespace/non-`#` characters -- long enough to be a real
# secret rather than a short placeholder (`token = "x"`, `token = "..."`) or
# a boolean/null.
_TOKEN_KEY_RE = re.compile(
    r"(?i)\b(" + "|".join(_TOKEN_KEY_NAMES) + r")\b\s*[:=]\s*"
    r"""["']?([^\s"'#]{8,})["']?"""
)

# HA long-lived access tokens are JWTs: three base64url segments joined by
# `.`. Real ones run well over 150 chars; requiring the whole match to be
# >= 180 chars keeps this from tripping on short dotted identifiers (a
# semver range, a dotted Python path, a version-pinned hash) that happen to
# have three `.`-separated segments.
_JWT_RE = re.compile(r"\b[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")
_JWT_MIN_LEN = 180

# `scheme://user:secret@host` -- credentials embedded directly in a URL
# (e.g. pasted into `ha_url`), bypassing both the keyring and `HASSLE_TOKEN`
# storage paths DESIGN §14 documents.
_URL_CREDENTIALS_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9+.-]*://[^\s/@\"']+:[^\s/@\"']+@")


def _scan_candidates(bundle_root: Path) -> list[Path]:
    candidates: list[Path] = []
    for path in sorted(bundle_root.rglob("*")):
        if not path.is_file():
            continue
        rel_parts = path.relative_to(bundle_root).parts[:-1]
        if any(part in _SKIP_DIR_NAMES for part in rel_parts):
            continue
        if path.suffix.lower() in _BINARY_SUFFIXES:
            continue
        try:
            if path.stat().st_size > _MAX_SCAN_BYTES:
                continue
        except OSError:
            continue
        candidates.append(path)
    return candidates


def find_committed_tokens(bundle_root: Path) -> list[tuple[Path, str]]:
    """Recursively scan the bundle for a committed HA token: a
    `token`/`access_token`/`ha_token`/`HASSLE_TOKEN`-shaped key assignment, a
    JWT-shaped literal (HA's own long-lived-token format) anywhere, or
    credentials embedded directly in a URL (`https://user:tok@host`). Skips
    `.git/`, `.venv/`, `typings/`, `__pycache__/`, `node_modules/` and
    binary-looking files.

    Returns `(path, reason)` pairs. `reason` is a short, safe-to-print
    category -- it never contains the matched secret value itself (DESIGN
    §14: the token must never appear in Hassle's own output)."""
    found: list[tuple[Path, str]] = []
    for path in _scan_candidates(bundle_root):
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        key_match = _TOKEN_KEY_RE.search(text)
        if key_match is not None:
            found.append((path, f"a `{key_match.group(1)}` key looks like a committed secret"))
            continue

        jwt_match = next(
            (m for m in _JWT_RE.finditer(text) if len(m.group(0)) >= _JWT_MIN_LEN), None
        )
        if jwt_match is not None:
            found.append((path, "a JWT-shaped string (HA long-lived tokens are JWTs)"))
            continue

        if _URL_CREDENTIALS_RE.search(text) is not None:
            found.append((path, "credentials embedded in a URL"))

    return found


def find_webhook_ids(objects: ObjectMap) -> list[str]:
    """Collect every `webhook_id` used by a `webhook` trigger across the
    bundle's already-compiled objects (DESIGN §14; SECURITY.md "What ends up
    in your repository"). A webhook ID is a bearer capability -- anyone who
    knows it can POST to `/api/webhook/<id>` with no authentication and fire
    that automation -- and `hassle pull` writes it verbatim into the bundle's
    committed Python (`webhook(<id>)`,
    `hassle.decompiler.exprs._trig_webhook`).

    This is purely informational: having webhook triggers is normal and
    unavoidable, so the caller must never fold this into `doctor`'s
    problem/exit-code tally -- it only tells the user how many exist so they
    know not to publish the bundle publicly."""
    ids: list[str] = []
    for _kind, config in objects.values():
        for trigger in config.get("triggers", None) or []:
            if isinstance(trigger, dict) and trigger.get("trigger") == "webhook":
                webhook_id = trigger.get("webhook_id")
                if webhook_id:
                    ids.append(str(webhook_id))
    return ids


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
