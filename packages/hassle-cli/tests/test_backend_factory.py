"""M7 review cleanup (M7.1 item 5a): `connect()` on an unregistered `fake://`
URL must raise a clean what/where/fix error instead of falling through to
`DirectBackend`, which would try to open a real connection to the literal
string `fake://<token>` and surface an ugly stack trace instead of a helpful
message. This is a test-only seam (docs: `hassle_cli.backend_factory`), but
its failure mode should still look like every other Hassle error.
"""

from __future__ import annotations

import pytest

from hassle_cli.backend_factory import UnregisteredFakeBackendError, connect


def test_unregistered_fake_url_raises_clean_error() -> None:
    with pytest.raises(UnregisteredFakeBackendError) as excinfo:
        with connect("fake://not-a-real-token", "unused-token"):
            pass  # pragma: no cover - must not get here
    message = str(excinfo.value)
    # what
    assert "fake://" in message
    assert "not-a-real-token" in message
    # fix
    assert "register_fake_backend" in message
