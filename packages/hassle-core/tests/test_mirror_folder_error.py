"""M9 error-message audit finding: `MediaMirror`'s "never target the media
root" guard previously lacked an explicit "Fix:" clause (R6)."""

from __future__ import annotations

import pytest

from hassle.backend.mirror import MediaMirror


class _StubTransport:
    def media_upload(self, folder: str, filename: str, data: bytes, content_type: str) -> str:
        raise AssertionError("not reached")  # pragma: no cover

    def media_resolve(self, media_content_id: str) -> tuple[str, str]:
        raise AssertionError("not reached")  # pragma: no cover

    def media_download(self, url: str) -> bytes:
        raise AssertionError("not reached")  # pragma: no cover

    def media_remove(self, media_content_id: str) -> None:
        raise AssertionError("not reached")  # pragma: no cover


@pytest.mark.parametrize("folder", ["", "/", ".", "  ", "//"])
def test_media_root_folder_raises_with_fix(folder: str) -> None:
    with pytest.raises(ValueError) as excinfo:
        MediaMirror(_StubTransport(), folder=folder)
    msg = str(excinfo.value)
    assert "media root" in msg  # what
    assert "Fix:" in msg


def test_real_subfolder_is_accepted() -> None:
    mirror = MediaMirror(_StubTransport(), folder="hassle")
    assert mirror is not None
