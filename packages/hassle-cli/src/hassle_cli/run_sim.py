"""`hassle run <target>` without `--live`: runs on the simulator (DESIGN §10.4
paragraph 5: "`hassle run` without `--live` runs the same thing on the
simulator").

`<target>` is `<relative/path.py>::<function_name>`, matching the object's
declared id in the compiled bundle (the function name, by DSL convention).
"""

from __future__ import annotations

from pathlib import Path

from hassle.testing import Simulator, simulate


class InvalidRunTargetError(ValueError):
    """`hassle run <target>` was given a target with no `::` separator
    (error messages state what/where/fix)."""

    def __init__(self, target: str) -> None:
        self.target = target
        super().__init__(
            f"`{target}` is not a valid run target: it has no `::` separator. Fix: use "
            f"`<relative/path.py>::<function_name>`, e.g. `automations/hallway.py::"
            f"hall_light_on_motion` (the function name is the automation's id, by DSL "
            f"convention)."
        )


class UnknownRunTargetError(KeyError):
    """`hassle run <target>` named a function not found in the compiled
    bundle (error messages state what/where/fix)."""

    def __init__(self, function_name: str, known: list[str]) -> None:
        self.function_name = function_name
        self.known = known
        known_names = ", ".join(sorted(k.partition(":")[2] for k in known)) or "(none)"
        super().__init__(
            f"no automation named `{function_name}` was found in the compiled bundle. "
            f"Fix: check the spelling, or pick one of the known automation function "
            f"names: {known_names}."
        )

    def __str__(self) -> str:
        # KeyError.__str__ re-reprs its args (Python quirk); the base
        # Exception message built above is the what/where/fix text -- surface
        # it directly instead of KeyError's usual double-quoted repr.
        return self.args[0]


def parse_target(target: str) -> tuple[str, str]:
    path_part, sep, name_part = target.partition("::")
    if not sep:
        raise InvalidRunTargetError(target)
    return path_part, name_part


def find_object_key(sim: Simulator, function_name: str) -> str:
    known = sim.automation_keys()
    for key in known:
        if key.endswith(f":{function_name}"):
            return key
    raise UnknownRunTargetError(function_name, known)


def run_on_simulator(bundle_root: Path, target: str) -> tuple[str, Simulator]:
    _path_part, function_name = parse_target(target)
    sim = simulate(bundle_root)
    object_key = find_object_key(sim, function_name)
    sim.fire(object_key)
    return object_key, sim
