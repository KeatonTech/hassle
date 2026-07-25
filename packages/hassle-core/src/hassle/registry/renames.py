"""Known pre-2026.7 purpose-vocabulary renames (DESIGN §4 quirks).

HA renamed several purpose-specific trigger/condition types between their Labs
debut and the 2026.7 stable vocabulary, **without migration** — old keys
simply stop working. Kept as DATA (never hard-coded logic), so a validator
run against an old bundle can point at the exact new name instead of just
saying "unknown".
"""

from __future__ import annotations

PURPOSE_RENAMES: dict[str, str] = {
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
