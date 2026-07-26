"""Remote-string sanitization (security hardening): HA-supplied strings --
aliases, entity ids, category names, version strings, error bodies -- must
never reach the terminal carrying a raw ANSI/control-code escape sequence.

Rich's own `STRIP_CONTROL_CODES` does not strip ESC (0x1B), and neither
`markup=False` nor `--plain`/`NO_COLOR` touch the raw bytes written to the
terminal -- so remote data could otherwise emit a sequence that rewrites the
terminal, hides text, or (on some terminals) manipulates the clipboard, even
through the CLI's existing markup-escaping (`_esc`/`rich.markup.escape`).

`hassle_cli.render.sanitize_for_terminal`/`safe_render` are the single choke
point every remote-string print routes through (module docstring). This file
covers the choke point itself; `test_plan_render_sanitization.py` covers
`hassle_cli.plan_render`'s three call sites.
"""

from __future__ import annotations

from hassle_cli.render import safe_render, sanitize_for_terminal

# The three payload shapes named in the audit finding.
CLEAR_SCREEN = "\x1b[2J"
SET_TITLE = "\x1b]0;title\x07"
CARRIAGE_RETURN_OVERWRITE = "\rPWNED"


def test_sanitize_strips_csi_escape_sequence() -> None:
    # The ESC byte is what makes a terminal treat the following `[2J` as a
    # clear-screen command rather than literal text -- stripping ESC (and
    # only ESC/control bytes, never printable ones) is what neutralizes it.
    out = sanitize_for_terminal(f"hallway light{CLEAR_SCREEN}")
    assert "\x1b" not in out
    assert out == "hallway light[2J"


def test_sanitize_strips_osc_title_sequence() -> None:
    out = sanitize_for_terminal(f"hallway light{SET_TITLE}")
    assert "\x1b" not in out
    assert "\x07" not in out
    assert out == "hallway light]0;title"


def test_sanitize_strips_bare_carriage_return() -> None:
    out = sanitize_for_terminal(f"hallway light{CARRIAGE_RETURN_OVERWRITE}")
    assert "\r" not in out
    assert out == "hallway lightPWNED"


def test_sanitize_keeps_tab_and_newline() -> None:
    out = sanitize_for_terminal("a\tb\nc")
    assert out == "a\tb\nc"


def test_sanitize_is_a_noop_on_plain_text() -> None:
    out = sanitize_for_terminal("automation:hall_light_on_motion")
    assert out == "automation:hall_light_on_motion"


def test_sanitize_strips_c1_control_range() -> None:
    # C1 controls (0x80-0x9F) are also valid ANSI escape starters on some
    # terminals (8-bit CSI is 0x9B) -- covered by the same choke point.
    out = sanitize_for_terminal("x\x9bAy")
    assert "\x9b" not in out
    assert out == "xAy"


def test_safe_render_sanitizes_and_escapes_markup() -> None:
    out = safe_render(f"[bold]{CLEAR_SCREEN}injected[/bold]")
    assert "\x1b" not in out
    # rich markup is escaped, not interpreted -- the literal brackets survive
    # as escaped text rather than being swallowed as a style tag.
    assert "bold" in out


def test_safe_render_accepts_non_string_values() -> None:
    # `_esc`'s callers pass exceptions, Path objects, etc. -- `safe_render`
    # must `str()` first, matching the old `_escape_markup(str(value))`
    # contract it replaced.
    out = safe_render(ValueError(f"boom{CLEAR_SCREEN}"))
    assert "\x1b" not in out
    assert "boom" in out
