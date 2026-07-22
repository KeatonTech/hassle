"""The `sim` pytest fixture (DESIGN §10.2).

Registered as a ``pytest11`` entry point on the ``hassle-core`` distribution
(see ``packages/hassle-core/pyproject.toml``), so any environment with
hassle-core installed gets the ``sim`` fixture automatically -- "plain
`pytest` works too" (DESIGN §10.2); `hassle test` is just `pytest` with
this plugin, which is already always loaded.

Bundle discovery: a real bundle's `tests/` directory sits one level below the
bundle root, so the default is "the parent directory of the pytest rootdir".
A test module can override this with the `@pytest.mark.hassle_bundle(path)`
marker (used by this repo's own in-tree tests, since the example bundles live
under `fixtures/sim/`, not next to `packages/hassle-core/tests/`).
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import pytest

from hassle.testing import Simulator, simulate


def _bundle_dir_for(request: pytest.FixtureRequest) -> Path:
    # `request.node` / `Node.get_closest_marker` are loosely typed in pytest's
    # own stubs (Unknown) -- silenced at this one boundary (pyright is strict
    # on hassle-core) rather than throughout the function.
    node = request.node  # pyright: ignore[reportUnknownVariableType, reportUnknownMemberType]
    marker = cast(
        "pytest.Mark | None",
        node.get_closest_marker("hassle_bundle"),  # pyright: ignore[reportUnknownMemberType]
    )
    if marker is not None:
        return Path(str(marker.args[0]))
    return Path(str(request.config.rootpath)).parent


@pytest.fixture
def sim(request: pytest.FixtureRequest) -> Simulator:
    """A fresh :class:`~hassle.testing.Simulator` per test, auto-compiling the bundle."""
    return simulate(_bundle_dir_for(request))
