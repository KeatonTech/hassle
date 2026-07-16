"""3-way DSL-level diff rendering for conflicts (DESIGN §8.2: "shown with a
3-way diff of the *decompiled DSL*, not JSON") and modernization-diff labeling.

Both features share the same building block: decompile a raw HA config dict
(local/remote/base) back to its DSL source text via the decompiler, then
diff the texts. Decompiling (not comparing JSON) is what makes a schema-only
difference (legacy singular `trigger:`/`service:` vs modern plural
`triggers:`/`action:`) invisible in the diff -- both forms decompile to
*identical* DSL, so the only remaining question is whether the underlying
configs are semantically identical (modernization) or not (a real conflict).
"""

from __future__ import annotations

import difflib
from typing import Any

from hassle.decompiler.codegen import decompile_object
from hassle.ir.models import parse


def _decompile_dsl(object_key: str, kind: str, config: dict[str, Any] | None) -> str:
    if config is None:
        return ""
    identity = object_key.partition(":")[2]
    obj = parse(config, kind=kind, key_hint=identity)
    return decompile_object(object_key, obj)


def dsl_diff(
    object_key: str, kind: str, local: dict[str, Any] | None, remote: dict[str, Any] | None
) -> str:
    """Unified diff of the decompiled DSL for `local` vs `remote`."""
    local_src = _decompile_dsl(object_key, kind, local)
    remote_src = _decompile_dsl(object_key, kind, remote)
    diff = difflib.unified_diff(
        remote_src.splitlines(keepends=True),
        local_src.splitlines(keepends=True),
        fromfile="remote",
        tofile="local",
    )
    return "".join(diff)


def is_modernization_only_diff(
    object_key: str, kind: str, local: dict[str, Any] | None, remote: dict[str, Any] | None
) -> bool:
    """True if `local` and `remote` differ only in legacy-vs-modern schema
    shape, not in any semantic way.

    Compares the *decompiled DSL* of both sides rather than the raw JSON:
    the compiler always emits the modern inner discriminator (`trigger:`/
    `action:`), but real HA never rewrites a legacy inner `platform:`/
    `service:` discriminator on storage (docs/ha-api-notes.md §17.1) -- so an
    adopted legacy-authored object's compiled (modern) form and its still-
    legacy remote form will keep differing at the JSON level even though
    they describe the exact same automation. The decompiler doesn't care
    which spelling it's given (both parse to the same typed builder call),
    so if both sides decompile to byte-identical DSL, the only difference is
    the one-time legacy->modern rewrite -- not something the user changed.
    """
    if local is None or remote is None:
        return False
    local_src = _decompile_dsl(object_key, kind, local)
    remote_src = _decompile_dsl(object_key, kind, remote)
    return local_src == remote_src and local != remote
