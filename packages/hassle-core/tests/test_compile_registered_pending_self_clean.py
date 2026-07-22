"""Regression: `compile_registered`'s dangling-declaration sweep must be
self-cleaning.

`compile_bundle` clears the pending-declaration list at the START of every
compile, so the CLI path was always safe. But a DIRECT `compile_registered`
caller had no such protection: after a compile raised
`DanglingTemplateHelperDeclarationError`, the unconsumed entry stayed in the
module-level pending list, and a later, perfectly clean direct call raised a
FALSE-POSITIVE for the previous call's ghost. Test isolation in
`test_template_helper_dangling_declaration.py` only held because of its own
autouse teardown — this file deliberately has NO such teardown between the
two compiles, pinning that the sweep itself cleans up (in a `finally`) so no
future direct caller has to remember to.
"""

from __future__ import annotations

import pytest

from hassle import template_sensor
from hassle.compiler import DanglingTemplateHelperDeclarationError
from hassle.compiler.bundle import compile_registered
from hassle.compiler.registry import current_registry, fresh
from hassle.compiler.template_helpers import _PENDING, reset_declared_template_helpers


@pytest.fixture(autouse=True)
def _reset_before_only():
    # Reset BEFORE each test for a clean start, but deliberately NOT between
    # the two compiles inside a test and NOT relying on teardown for the
    # leak check itself.
    reset_declared_template_helpers()
    fresh()
    yield
    reset_declared_template_helpers()
    fresh()


def _compile_current() -> object:
    return compile_registered(list(current_registry().objects), list(current_registry().prebuilt))


def test_clean_compile_after_dangling_failure_does_not_false_positive() -> None:
    template_sensor(name="Ghost One")  # dangling: no state=, never decorated
    with pytest.raises(DanglingTemplateHelperDeclarationError):
        _compile_current()

    # Same process, NO manual reset in between (the point of the regression):
    # a clean, unrelated direct compile must not re-raise for "Ghost One".
    fresh()
    template_sensor(name="Real Sensor", state="{{ 1 }}")
    result = _compile_current()
    assert result is not None


def test_sweep_clears_pending_on_failure() -> None:
    template_sensor(name="Ghost Two")
    with pytest.raises(DanglingTemplateHelperDeclarationError):
        _compile_current()
    assert _PENDING == []


def test_sweep_clears_pending_on_success() -> None:
    @template_sensor(name="Decorated Sensor")
    def decorated_sensor():  # pyright: ignore[reportUnusedFunction]
        return "{{ 2 }}"

    _compile_current()
    assert _PENDING == []
