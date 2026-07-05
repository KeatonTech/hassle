"""`hassle login`'s auth-probe seam: imported as `hassle_cli.commands.login.
DirectBackend` so tests can monkeypatch just this reference (avoiding a real
network probe) without touching the real `hassle.backend.DirectBackend`
used everywhere else.
"""

from __future__ import annotations

from hassle.backend import DirectBackend

__all__ = ["DirectBackend"]
