"""Canonical JSON serialization and object hashing (part of the frozen IR schema; deterministic).

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


#: HA storage-collection normalization parity: without this, every pushed
#: helper would show as changed on every subsequent plan, forever. HA coerces
#: input_number numerics to float, fills these defaults when unset, and
#: stores timer durations as H:MM:SS without hour zero-padding. Applied when
#: COMPARING/HASHING for sync (never to compiled output -- compile(
#: decompile(x)) round-trips stay byte-exact).
_STORAGE_FLOAT_FIELDS = {"input_number": ("min", "max", "step", "initial")}
_STORAGE_DEFAULTS = {
    "input_number": {"mode": "slider", "step": 1},
    "input_text": {"mode": "text", "min": 0, "max": 100},
    "timer": {"restore": False, "duration": "0:00:00"},
    "counter": {"restore": True, "initial": 0, "step": 1},
}


def storage_canonical(kind: str, config: dict[str, Any]) -> dict[str, Any]:
    """`config` as real HA would store it, for sync comparison. Identity for
    kinds without known normalization (automations, scripts, template
    helpers -- the latter are already coerced at compile time)."""
    if kind not in _STORAGE_FLOAT_FIELDS and kind not in _STORAGE_DEFAULTS:
        return config
    out = dict(config)
    # Defaults FIRST, coercion second: a defaulted input_number step must
    # come out as HA's float 1.0, not int 1 -- dict equality treats them the
    # same but canonical JSON (and therefore every hash) does not.
    # Counter/input_text defaults stay int: those kinds are
    # not in the float-fields map.
    for field, default in _STORAGE_DEFAULTS.get(kind, {}).items():
        out.setdefault(field, default)
    for field in _STORAGE_FLOAT_FIELDS.get(kind, ()):
        if field in out and isinstance(out[field], (int, float)):
            out[field] = float(out[field])
    if kind == "timer":
        duration = out.get("duration")
        total: int | None = None
        if isinstance(duration, (int, float)) and not isinstance(duration, bool):
            total = int(duration)
        elif isinstance(duration, str):
            parts = duration.split(":")
            if len(parts) == 3 and all(x.isdigit() for x in parts):
                h, m, sec = (int(x) for x in parts)
                total = h * 3600 + m * 60 + sec
        if total is not None:
            # str(timedelta) shape, HA's stored form -- including the
            # "1 day, 1:00:00" rendering past 24 hours.
            days, rem = divmod(total, 86400)
            h, rem = divmod(rem, 3600)
            m, sec = divmod(rem, 60)
            base_str = f"{h}:{m:02d}:{sec:02d}"
            if days == 1:
                base_str = f"1 day, {base_str}"
            elif days > 1:
                base_str = f"{days} days, {base_str}"
            out["duration"] = base_str
    return out
