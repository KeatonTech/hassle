"""Canonical JSON serialization and object hashing (F1, R8).

The canonical form is deterministic and byte-stable across runs and platforms:

- dict keys are sorted recursively (key order is *not* semantically meaningful);
- list order is preserved (list order *is* semantically meaningful);
- no insignificant whitespace, and non-ASCII characters are emitted verbatim.

`sha256_hash` is the object hash used as the three-way-merge base in the sync
engine (DESIGN §8.1); it carries a ``sha256:`` prefix to match ``manifest.lock``.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(data: Any) -> str:
    """Return the canonical JSON string for ``data`` (sorted keys, compact)."""
    return json.dumps(
        data,
        sort_keys=True,
        ensure_ascii=False,
        separators=(",", ":"),
    )


def sha256_hash(data: Any) -> str:
    """Return ``sha256:<hexdigest>`` of the canonical JSON of ``data``."""
    digest = hashlib.sha256(canonical_json(data).encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
