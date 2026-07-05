"""Rich output with a plain-text capture mode (NO_COLOR/--plain, MILESTONES M7:
"Rich output must have a plain-text capture mode for snapshot tests").

`get_console()` builds a `rich.console.Console` honoring both the `NO_COLOR`
env var (https://no-color.org, checked by Rich itself) and an explicit
`--plain` CLI flag (`force_plain=True`): either disables color/highlighting
and fixes a stable width so snapshot output never wraps differently across
terminals/CI runners.
"""

from __future__ import annotations

import io
import os
from collections.abc import Callable

from rich.console import Console

SNAPSHOT_WIDTH = 100


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
    the captured output (no ANSI codes) -- the plain-capture helper the
    milestone asks for, usable directly in unit tests without going through
    a full CLI invocation."""
    buffer = io.StringIO()
    console = Console(file=buffer, no_color=True, force_terminal=False, width=SNAPSHOT_WIDTH)
    fn(console)
    return buffer.getvalue()
