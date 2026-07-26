"""The simulator's Jinja environment must be sandboxed.

Templates reach the simulator straight from Home Assistant config (pulled into
the bundle verbatim), and `hassle test`/`hassle run` render them locally. A
plain `jinja2.Environment` allows attribute traversal from any object to
Python builtins, so a stored template would be able to run arbitrary code on
the machine running the tests. Home Assistant renders the same templates in a
`SandboxedEnvironment`; Hassle should be no weaker.
"""

from __future__ import annotations

import datetime

import jinja2.sandbox
import pytest

from hassle.testing.errors import UnsupportedTemplateError
from hassle.testing.state import StateStore
from hassle.testing.templates import TemplateEngine

# Each of these reaches Python internals through a different Jinja global or
# builtin type, so they fail independently if the sandbox regresses.
ESCAPES = [
    "{{ ''.__class__ }}",
    "{{ ''.__class__.__mro__[1].__subclasses__() | length }}",
    "{{ cycler.__init__.__globals__ }}",
    "{{ namespace.__init__.__globals__ }}",
    "{{ cycler.__init__.__globals__.__builtins__.__import__('os').popen('id').read() }}",
    "{{ ().__class__.__bases__[0].__subclasses__() | length }}",
    "{{ lipsum.__globals__ }}",
    "{{ self.__init__.__globals__ }}",
]


def _engine() -> TemplateEngine:
    return TemplateEngine(StateStore(), lambda: datetime.datetime(2026, 1, 1, 12, 0))


def test_environment_is_sandboxed() -> None:
    engine = _engine()
    env = engine._env  # pyright: ignore[reportPrivateUsage]
    assert isinstance(env, jinja2.sandbox.SandboxedEnvironment), (
        "the simulator must use jinja2.sandbox.SandboxedEnvironment"
    )


@pytest.mark.parametrize("template", ESCAPES)
def test_sandbox_escapes_are_refused(template: str) -> None:
    """Each payload must be refused, not silently rendered."""
    engine = _engine()
    with pytest.raises((UnsupportedTemplateError, jinja2.exceptions.SecurityError)):
        engine.render(template)


def test_ordinary_templates_still_render() -> None:
    """The sandbox must not break the templates people actually write."""
    states = StateStore()
    states.set("sensor.temp", "21.5")
    engine = TemplateEngine(states, lambda: datetime.datetime(2026, 1, 1, 12, 0))
    assert engine.render("{{ states('sensor.temp') }}") == "21.5"
    assert engine.render("{{ (states('sensor.temp') | float) + 1 }}") == "22.5"
    assert engine.render("{{ 'on' if is_state('sensor.temp', '21.5') else 'off' }}") == "on"
    assert engine.render("{{ now().year }}") == "2026"
    assert engine.render("{% for i in [1, 2] %}{{ i }}{% endfor %}") == "12"
