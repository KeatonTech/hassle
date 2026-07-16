"""MILESTONES M6 test 9 — the optional media mirror (DESIGN §8.5, §4 quirks).

- Upload ZIP bytes under a media extension (both gates handled: upload
  Content-Type is `image/`, download name is a media extension), resolve +
  download bytes identical, remove works.
- Target-folder creation: verified behaviorally that upload auto-creates the
  subfolder (`mkdir(parents=True, exist_ok=True)`, docs/ha-api-notes.md §17 —
  correcting the M0.V §10.4 "upload does not mkdir" note). The mirror never
  targets the media root (its signed URLs are broken — §10.4).
- A tightened/failed gate (a disallowed Content-Type → HTTP 400) surfaces as a
  `MirrorError` and leaves sync completely unaffected (the mirror is isolated).
"""

from __future__ import annotations

import pytest

from hassle.backend import DirectBackend
from hassle.backend.mirror import MediaMirror, MirrorError

_ZIP = b"PK\x03\x04" + b"hassle-bundle-mirror-roundtrip-payload" * 8


def test_mirror_push_pull_remove_roundtrip(ha: DirectBackend) -> None:
    mirror = MediaMirror(ha, folder="hassle_test")
    mirror.push(_ZIP)
    try:
        fetched = mirror.pull()
        assert fetched == _ZIP, "mirror round-trip corrupted the bytes"
    finally:
        mirror.remove()
    # After remove, pull fails (nothing there) — cleanly, as a MirrorError.
    with pytest.raises(MirrorError):
        mirror.pull()


def test_mirror_never_targets_media_root(ha: DirectBackend) -> None:
    with pytest.raises(ValueError):
        MediaMirror(ha, folder="")
    with pytest.raises(ValueError):
        MediaMirror(ha, folder=".")


def test_tightened_gate_raises_mirror_error_and_sync_unaffected(ha: DirectBackend) -> None:
    # Simulate a tightened upload gate by forcing a disallowed Content-Type
    # (application/zip → 400, per §4). The mirror surfaces MirrorError...
    mirror = MediaMirror(ha, folder="hassle_test", upload_content_type="application/zip")
    with pytest.raises(MirrorError):
        mirror.push(_ZIP)

    # ...and sync is completely unaffected: normal backend ops still work.
    # (HA derives a helper's id from its name slug, so use the returned identity.)
    identity = ha.create("input_boolean", {"name": "Still Fine"})
    assert identity in ha.list_remote("input_boolean")
