"""Reviewer note on PR #21: `_is_undefined_render_error` keys on two jinja2
message substrings re-embedded through `TemplateEngine.render`'s `reason=`.
Nothing pinned those shapes, so a future refactor of the error formatting
would silently turn the timeout-path condition swallow back into a raise,
detectable only via one cookbook integration test. These unit tests make the
drift local and obvious."""

from __future__ import annotations

from hassle.testing.actions import _is_undefined_render_error  # pyright: ignore[reportPrivateUsage]
from hassle.testing.errors import UnsupportedTemplateError
from hassle.testing.state import StateStore
from hassle.testing.templates import TemplateEngine


def _render_error(template: str) -> UnsupportedTemplateError:
    engine = TemplateEngine(StateStore(), clock_now=lambda: 0.0)
    try:
        engine.render(template)
    except UnsupportedTemplateError as exc:
        return exc
    raise AssertionError(f"expected {template!r} to raise")


def test_undefined_name_shape_is_recognized() -> None:
    exc = _render_error("{{ totally_undefined_name }}")
    assert _is_undefined_render_error(exc)


def test_none_attribute_shape_is_recognized() -> None:
    exc = _render_error("{{ none.deep.attribute }}")
    assert _is_undefined_render_error(exc)


def test_unknown_filter_shape_is_not_swallowed() -> None:
    exc = _render_error("{{ 1 | some_unknown_filter }}")
    assert not _is_undefined_render_error(exc)
