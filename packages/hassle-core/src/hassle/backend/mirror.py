"""The optional in-HA media mirror (DESIGN §8.5, §4 quirks; MILESTONES M6 test 9).

`hassle mirror push/pull` stashes the bundle ZIP inside HA's local media storage
so a copy of sources+tests lives *inside* HA (and its backups, if the user
enables the Media toggle). It is **best-effort and fully isolated**: every
failure surfaces as a `MirrorError` the CLI degrades to a warning, and nothing
else in Hassle ever depends on it (DESIGN §8.5, §15).

The mechanism rides two incidental HA gates (docs/ha-api-notes.md §9, §10.3, §17):

1. **Upload Content-Type gate** — the upload endpoint only accepts a multipart
   part whose ``Content-Type`` starts with ``image/``/``video/``/``audio/``
   (bytes and extension are ignored on upload). So we send ``image/png``.
2. **Download extension gate** — the authenticated media view 404s unless the
   *filename extension* maps to an image/video/audio MIME type. So the ZIP is
   stored under a media extension (``.mp3`` by default; the bytes are unchanged).

Both must pass for a round-trip. The target subfolder is auto-created by the
upload endpoint (``mkdir(parents=True, exist_ok=True)`` — docs/ha-api-notes.md
§17, correcting the M0.V §10.4 "upload does not mkdir" note), so the mirror does
not need to pre-create it. The mirror never targets the media root (its signed
URLs are broken — §10.4); an empty or ``.`` folder is rejected up front.
"""

from __future__ import annotations

from typing import Protocol

from hassle.backend.errors import HaError


class MirrorError(Exception):
    """Any mirror operation failed. The CLI degrades this to a warning (§8.5)."""


class _MediaTransport(Protocol):
    """The slice of `DirectBackend` the mirror needs (keeps it decoupled/testable)."""

    def media_upload(self, folder: str, filename: str, data: bytes, content_type: str) -> str: ...
    def media_resolve(self, media_content_id: str) -> tuple[str, str]: ...
    def media_download(self, url: str) -> bytes: ...
    def media_remove(self, media_content_id: str) -> None: ...


class MediaMirror:
    """Best-effort ZIP mirror into HA's local media storage (§8.5)."""

    def __init__(
        self,
        transport: _MediaTransport,
        *,
        folder: str = "hassle",
        filename: str = "hassle-bundle.mp3",
        upload_content_type: str = "image/png",
    ) -> None:
        clean = folder.strip().strip("/")
        if not clean or clean == ".":
            raise ValueError(
                "the media mirror must target a subfolder, never the media root "
                "(its signed URLs are broken — docs/ha-api-notes.md §10.4)"
            )
        self._transport = transport
        self._folder = clean
        self._filename = filename
        self._upload_content_type = upload_content_type

    @property
    def media_content_id(self) -> str:
        return f"media-source://media_source/local/{self._folder}/{self._filename}"

    def push(self, zip_bytes: bytes) -> None:
        """Upload ``zip_bytes`` to the mirror (both gates handled)."""
        try:
            self._transport.media_upload(
                self._folder, self._filename, zip_bytes, self._upload_content_type
            )
        except (HaError, MirrorError) as err:
            raise MirrorError(
                f"mirror push failed uploading to {self.media_content_id}: {err}. "
                "The mirror is best-effort (DESIGN §8.5) — sync is unaffected."
            ) from err

    def pull(self) -> bytes:
        """Resolve and download the mirrored ZIP bytes."""
        try:
            url, _mime = self._transport.media_resolve(self.media_content_id)
            return self._transport.media_download(url)
        except (HaError, MirrorError) as err:
            raise MirrorError(
                f"mirror pull failed fetching {self.media_content_id}: {err}. "
                "The mirror is best-effort (DESIGN §8.5) — sync is unaffected."
            ) from err

    def remove(self) -> None:
        try:
            self._transport.media_remove(self.media_content_id)
        except (HaError, MirrorError) as err:
            raise MirrorError(
                f"mirror remove failed for {self.media_content_id}: {err}. "
                "The mirror is best-effort (DESIGN §8.5) — sync is unaffected."
            ) from err
