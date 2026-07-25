"""Rich output with a plain-text capture mode (NO_COLOR/--plain): rich output
must have a plain-text capture mode for snapshot tests.

`get_console()` builds a `rich.console.Console` honoring both the `NO_COLOR`
env var (https://no-color.org, checked by Rich itself) and an explicit
`--plain` CLI flag (`force_plain=True`): either disables color/highlighting
and fixes a stable width so snapshot output never wraps differently across
terminals/CI runners.

**Remote-string sanitization (single choke point).** Every string this CLI
prints that ultimately comes from Home Assistant -- an alias, an entity id,
a category name, a version string, an API error body -- must go through
:func:`sanitize_for_terminal` (or :func:`safe_render`, which also does rich
markup escaping) before it reaches `Console.print`. Rich's own
`STRIP_CONTROL_CODES` does not strip ESC (0x1B), and neither `markup=False`
nor `--plain`/`NO_COLOR` touch the raw bytes written to the terminal either
-- so without this, HA-supplied data can carry an ANSI escape sequence that
rewrites the terminal, hides text, or (on some terminals) manipulates the
clipboard. `hassle_cli.plan_render` and `hassle_cli.cli`'s `_esc` both route
through this module rather than each rolling their own stripping.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Callable

from rich.console import Console
from rich.markup import escape as _escape_markup

SNAPSHOT_WIDTH = 100

# C0 controls except tab (\x09) and newline (\x0a), DEL, and the C1 range --
# i.e. every control character that isn't needed for plain multi-line text,
# including ESC (\x1b, the start of every ANSI escape sequence) and CR
# (\x0d, a bare terminal-line overwrite). See the module docstring.
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def sanitize_for_terminal(text: str) -> str:
    """Strip C0/C1 control characters (except tab/newline) from ``text``.

    Use on any Home-Assistant-supplied string before it is written to the
    terminal, even under ``markup=False`` -- stripping control bytes is a
    different concern from rich markup escaping, and Rich does neither for
    you (module docstring). Idempotent and safe on plain ASCII/Python text
    (a no-op).
    """
    return _CONTROL_CHARS_RE.sub("", text)


def safe_render(value: object) -> str:
    """Sanitize control characters, then escape rich markup, so ``value``
    (any Home-Assistant-supplied string: alias, entity id, category name,
    version, error body, ...) can be safely interpolated into a still
    markup-enabled f-string passed to ``Console.print``. For a string being
    printed with ``markup=False`` already (e.g. a decompiled DSL diff),
    :func:`sanitize_for_terminal` alone is enough -- escaping brackets there
    would corrupt the printed text, since nothing is parsing them as markup.
    """
    return _escape_markup(sanitize_for_terminal(str(value)))


def get_console(*, force_plain: bool = False, file: io.IOBase | None = None) -> Console:
    no_color = force_plain or bool(os.environ.get("NO_COLOR"))
    return Console(
        file=file,  # type: ignore[arg-type]
        no_color=no_color,
        force_terminal=False if no_color else None,
        highlight=not no_color,
        width=SNAPSHOT_WIDTH,
        color_system=None if no_color else "auto",
    )


def render_plain(fn: Callable[[Console], None]) -> str:
    """Run `fn(console)` against an in-memory plain-text console and return
    the captured output (no ANSI codes) -- usable directly in unit tests
    without going through a full CLI invocation."""
    buffer = io.StringIO()
    console = Console(file=buffer, no_color=True, force_terminal=False, width=SNAPSHOT_WIDTH)
    fn(console)
    return buffer.getvalue()
