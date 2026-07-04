"""M3: the known pre-2026.7 purpose-vocabulary renames table (DESIGN §4 quirks).

Kept as DATA (a dict), not scattered logic, per the milestone brief. Exact table
from MILESTONES M3 test 2b.
"""

from __future__ import annotations

from hassle.registry.renames import PURPOSE_RENAMES


def test_renames_table_exact_entries() -> None:
    expected = {
        "battery.low": "battery.became_low",
        "battery.not_low": "battery.no_longer_low",
        "lawn_mower.docked": "lawn_mower.returned_to_dock",
        "schedule.turned_off": "schedule.block_ended",
        "schedule.turned_on": "schedule.block_started",
        "timer.time_remaining": "timer.remaining_time_reached",
        "update.update_became_available": "update.became_available",
        "vacuum.docked": "vacuum.returned_to_dock",
        "climate.target_humidity": "climate.is_target_humidity",
        "climate.target_temperature": "climate.is_target_temperature",
    }
    assert PURPOSE_RENAMES == expected
