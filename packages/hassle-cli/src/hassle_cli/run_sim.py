"""`hassle run <target>` without `--live`: runs on the simulator (DESIGN §10.4
paragraph 5: "`hassle run` without `--live` runs the same thing on the
simulator").

`<target>` is `<relative/path.py>::<function_name>`, matching the object's
declared id in the compiled bundle (the function name, by DSL convention).
"""

from __future__ import annotations

from pathlib import Path

from hassle.testing import Simulator, simulate


def parse_target(target: str) -> tuple[str, str]:
    path_part, sep, name_part = target.partition("::")
    if not sep:
        raise ValueError(f"invalid run target {target!r}: expected '<path.py>::<function_name>'")
    return path_part, name_part


def find_object_key(sim: Simulator, function_name: str) -> str:
    for key in sim._engines_by_key:
        if key.endswith(f":{function_name}"):
            return key
    raise KeyError(
        f"no automation named {function_name!r} in the compiled bundle "
        f"(known: {sorted(sim._engines_by_key)})"
    )


def run_on_simulator(bundle_root: Path, target: str) -> tuple[str, Simulator]:
    _path_part, function_name = parse_target(target)
    sim = simulate(bundle_root)
    object_key = find_object_key(sim, function_name)
    sim.fire(object_key)
    return object_key, sim
