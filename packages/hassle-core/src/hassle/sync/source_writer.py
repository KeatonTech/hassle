"""The `SourceWriter` seam (F2) — DESIGN §7.3, §8.3.

`SourceWriter` decouples the sync engine's pull-side (bundle-side) actions from
M2's LibCST-based splicer, which lives on a parallel, not-yet-merged branch.
M5's pull engine (:mod:`hassle.sync.pull`) only depends on this Protocol; M2
will provide a real implementation that surgically replaces one object's
definition in place, preserving the rest of the file byte-for-byte (DESIGN §7.3
test 4, `test_splice_preserves_rest_of_file`) — that fidelity is out of scope
here. M5 ships two implementations:

- `WholeFileSourceWriter` — a blunt, whole-file overwrite. Correct (if not
  surgical) for `adopt` (a brand new file has no "rest of file" to preserve)
  and an acceptable stand-in for `refresh`/`drop` until M2 lands.
- `RecordingSourceWriter` — an in-memory test double that records every call
  without touching disk, used by the pull-engine unit tests.

Conflict marker format (used by the pull engine when writing a CONFLICT entry,
documented here since `SourceWriter` is the seam that receives it): a simple
textual 3-way marker block, deliberately NOT git's real conflict-marker syntax
(so it can never be confused with an actual git conflict by tooling):

    <<<<<<< local
    {local config, pretty-printed}
    =======
    {remote config, pretty-printed}
    >>>>>>> remote

M7 owns real conflict UX (rich 3-way DSL diff rendering); this is only the
structured data plumbed through to a human/M7-readable placeholder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class SourceWriter(Protocol):
    """What the pull engine needs to mutate the working tree (F2)."""

    def write_whole_file(self, path: Path, content: str) -> None:
        """Create or fully overwrite ``path`` with ``content``."""
        ...

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        """Replace just the definition for ``object_key`` within ``path``.

        M5's `WholeFileSourceWriter` implements this as a whole-file overwrite;
        M2's real splicer replaces only the matching `def`/decorator block.
        """
        ...

    def delete_object(self, path: Path, object_key: str) -> None:
        """Remove ``object_key``'s source (drop). May delete the whole file."""
        ...


class WholeFileSourceWriter:
    """Blunt but correct: every operation is a whole-file write or delete."""

    def write_whole_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        # M5 stand-in: no LibCST splicer available yet, so this overwrites the
        # whole file. `object_key` is accepted (part of the Protocol) but
        # unused by this implementation.
        del object_key
        self.write_whole_file(path, content)

    def delete_object(self, path: Path, object_key: str) -> None:
        del object_key
        if path.exists():
            path.unlink()


class RecordingSourceWriter:
    """In-memory test double: records calls, never touches disk."""

    def __init__(self) -> None:
        self.written_files: dict[Path, str] = {}
        self.spliced_objects: list[tuple[Path, str, str]] = []
        self.deleted_objects: list[tuple[Path, str]] = []

    def write_whole_file(self, path: Path, content: str) -> None:
        self.written_files[path] = content

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        self.spliced_objects.append((path, object_key, content))

    def delete_object(self, path: Path, object_key: str) -> None:
        self.deleted_objects.append((path, object_key))
