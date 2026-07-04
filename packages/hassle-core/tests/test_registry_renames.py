"""M3: the known pre-2026.7 purpose-vocabulary renames table (DESIGN §4 quirks).

Kept as DATA (a dict), not scattered logic, per the milestone brief. Exact table
from MILESTONES M3 test 2b.
"""

from __future__ import annotations

from pathlib import Path

from hassle.registry.renames import PURPOSE_RENAMES
from hassle.registry.snapshot import RegistrySnapshot

FIXTURE = Path(__file__).resolve().parents[3] / "fixtures" / "registry" / "home.json"


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
    assert expected == PURPOSE_RENAMES


def test_every_rename_target_is_in_the_fixture_vocabulary() -> None:
    """(reviewer N1) A user migrating `battery.low` -> `battery.became_low` (etc.)
    must land on a key the registry snapshot actually recognizes -- otherwise
    fixing the rename just trades one Finding (`renamed-purpose-type`) for
    another (`unknown-purpose-type`). Every RHS of `PURPOSE_RENAMES` must be
    enumerated somewhere in the fixture's `purpose_vocabulary` (trigger targets
    checked against `triggers`, condition targets against `conditions`).
    """
    snapshot = RegistrySnapshot.load(FIXTURE)
    known_triggers = set(snapshot.purpose_vocabulary.triggers)
    known_conditions = set(snapshot.purpose_vocabulary.conditions)
    known = known_triggers | known_conditions
    missing = sorted(target for target in PURPOSE_RENAMES.values() if target not in known)
    assert not missing, f"rename targets missing from fixture purpose_vocabulary: {missing}"
