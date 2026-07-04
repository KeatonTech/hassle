"""Ensures this tests directory is importable (so `import _corpus` resolves).

Also enforces the M4 simulator determinism marker (MILESTONES M4 test 5, R8):
"no test may take > 1s wall-clock" -- since the simulator's clock is fake, any
`test_sim_*.py` test taking that long is a real-sleep regression, not a slow
assertion, and CI must fail loudly rather than just being slow.
"""

from __future__ import annotations

import time
from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _enforce_sim_test_wall_clock_budget(request: pytest.FixtureRequest) -> Generator[None]:
    path = str(request.node.fspath)
    if "test_sim_" not in path:
        yield
        return
    start = time.monotonic()
    yield
    elapsed = time.monotonic() - start
    assert elapsed < 1.0, (
        f"{request.node.nodeid} took {elapsed:.3f}s wall-clock; M4 simulator tests must run "
        f"in well under 1s since the clock is fake (R8) -- a real `time.sleep`/network call "
        f"regressed in, or the simulator is doing unbounded work advancing the clock."
    )
