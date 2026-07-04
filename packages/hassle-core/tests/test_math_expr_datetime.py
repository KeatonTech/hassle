"""M1.1 -- datetime helpers (MILESTONES M1.1 deliverables): as_datetime,
timedelta_, as_timestamp, today_at. Each mirrors an HA Jinja extension 1:1,
same convention as the trig/round builders (bare function-call rendering).
"""

from __future__ import annotations

from hassle.compiler.math_expr import as_datetime, as_timestamp, timedelta_, today_at
from hassle.compiler.templates import var


def test_as_datetime_renders_function_call() -> None:
    result = as_datetime(var("wakeup_time"))
    assert result.to_template() == "{{ as_datetime(wakeup_time) }}"


def test_as_timestamp_renders_function_call() -> None:
    result = as_timestamp(var("event_time"))
    assert result.to_template() == "{{ as_timestamp(event_time) }}"


def test_today_at_renders_function_call() -> None:
    result = today_at("06:30:00")
    assert result.to_template() == "{{ today_at('06:30:00') }}"


def test_today_at_composes_with_arithmetic() -> None:
    result = today_at("06:30:00") + timedelta_(minutes=30)
    assert result.to_template() == "{{ today_at('06:30:00') + timedelta(minutes=30) }}"


def test_timedelta_multiple_units() -> None:
    result = timedelta_(hours=1, minutes=30)
    assert result.to_template() == "{{ timedelta(hours=1, minutes=30) }}"
