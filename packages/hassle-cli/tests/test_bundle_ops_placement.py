"""M7.1: pull/adopt placement for never-seen objects follows DESIGN §7.3's
tree defaults (``automations/misc.py`` etc.), not the flat one-file-per-object
layout the M7 §17.9 finding worked around while the loader was non-recursive.
"""

from __future__ import annotations

from hassle_cli.bundle_ops import default_source_path


def test_default_source_path_places_automation_under_automations_misc() -> None:
    assert default_source_path("automation:hall_light_on_motion") == "automations/misc.py"


def test_default_source_path_places_script_under_scripts_misc() -> None:
    assert default_source_path("script:movie_time") == "scripts/misc.py"


def test_default_source_path_places_helpers_under_helpers_misc() -> None:
    assert default_source_path("input_boolean:guest_mode") == "helpers/misc.py"
    assert default_source_path("counter:door_opens") == "helpers/misc.py"
    assert default_source_path("timer:cooldown") == "helpers/misc.py"
