"""3-way DSL-level diff rendering for conflicts (DESIGN §8.2: "shown with a
3-way diff of the *decompiled DSL*, not JSON") and modernization-diff labeling
(MILESTONES M7 test 4b, the M2 review finding).

Both features share the same building block: decompile a raw HA config dict
(local/remote/base) back to its DSL source text via M2's decompiler, then
diff the texts. Decompiling (not comparing JSON) is what makes a schema-only
difference (legacy singular `trigger:`/`service:` vs modern plural
`triggers:`/`action:`) invisible in the diff -- both forms decompile to
*identical* DSL, so the only remaining question is whether the underlying
configs are semantically identical (modernization) or not (a real conflict).
"""

from __future__ import annotations

import difflib
import re
from typing import Any

from hassle.decompiler.codegen import decompile_object
from hassle.ir.models import parse


def decompile_dsl(object_key: str, kind: str, config: dict[str, Any] | None) -> str:
    """Decompile one side of a conflict to its DSL source text.

    Public (`ux/conflict-difftool`): the external-difftool path
    (`hassle_cli.difftool`) writes exactly this -- byte-exact, never
    display-wrapped -- to the temp files it hands the diff tool.
    """
    if config is None:
        return ""
    identity = object_key.partition(":")[2]
    obj = parse(config, kind=kind, key_hint=identity)
    return decompile_object(object_key, obj)


# Display-only wrapping of very long single-string values in the INLINE diff
# (`ux/conflict-difftool`): a template sensor whose state is a single 8KB
# Jinja string decompiles to one enormous line, so a one-character remote
# edit renders as a full-string -/+ pair that shows nothing about WHICH part
# changed. Breaking both sides at Jinja tag boundaries before diffing turns
# unchanged segments into context lines and isolates the changed segment as
# its own -/+ pair. `{% %}` block tags are the natural statement boundaries;
# a template with no blocks at all falls back to `{{ }}` expression starts.
# The wrap threshold matches the workspace line-length (100): anything the
# repo's own style would allow on one line stays on one line.
_JINJA_WRAP_MIN_LEN = 100
_JINJA_BLOCK_START = re.compile(r"(?=\{%)")
_JINJA_EXPR_START = re.compile(r"(?=\{\{)")


def _display_wrap_line(line: str) -> list[str]:
    if len(line) <= _JINJA_WRAP_MIN_LEN:
        return [line]
    if "{%" in line:
        pattern = _JINJA_BLOCK_START
    elif "{{" in line:
        pattern = _JINJA_EXPR_START
    else:
        return [line]  # long but not Jinja (a wide @automation(...) row): untouched
    parts = [part for part in pattern.split(line) if part]
    if len(parts) <= 1:
        return [line]
    indent = line[: len(line) - len(line.lstrip())]
    return [parts[0], *(f"{indent}  {part}" for part in parts[1:])]


def _wrap_jinja_for_display(src: str) -> str:
    wrapped: list[str] = []
    for line in src.splitlines():
        wrapped.extend(_display_wrap_line(line))
    return "".join(f"{line}\n" for line in wrapped)


def dsl_diff(
    object_key: str, kind: str, local: dict[str, Any] | None, remote: dict[str, Any] | None
) -> str:
    """Unified diff of the decompiled DSL for `local` vs `remote` -- for
    inline display only (both sides are display-wrapped at Jinja boundaries;
    see `_wrap_jinja_for_display`)."""
    local_src = _wrap_jinja_for_display(decompile_dsl(object_key, kind, local))
    remote_src = _wrap_jinja_for_display(decompile_dsl(object_key, kind, remote))
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
    shape, not in any semantic way (MILESTONES M7 test 4b).

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
    local_src = decompile_dsl(object_key, kind, local)
    remote_src = decompile_dsl(object_key, kind, remote)
    return local_src == remote_src and local != remote
