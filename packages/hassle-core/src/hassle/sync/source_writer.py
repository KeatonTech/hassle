"""The `SourceWriter` seam (F2) — DESIGN §7.3, §8.3.

`SourceWriter` decouples the sync engine's pull-side (bundle-side) actions from
M2's LibCST-based splicer. M5's pull engine (:mod:`hassle.sync.pull`) only
depends on this Protocol. Three implementations:

- `SplicingSourceWriter` — the real one (what `hassle pull` uses): `refresh`
  surgically replaces one object's definition in place and `drop` removes only
  that object's statement, preserving the rest of the file byte-for-byte
  (DESIGN §7.3 test 4, `test_splice_preserves_rest_of_file`), via
  :mod:`hassle.decompiler.splice`.
- `WholeFileSourceWriter` — a blunt, whole-file overwrite. Correct (if not
  surgical) for `adopt` (a brand new file has no "rest of file" to preserve).
  It was the M5 stand-in for `refresh`/`drop` too — using it for those on a
  file holding MORE than one object silently clobbers the siblings (the
  `test_pull_refresh_splice.py` regression for refresh's whole-file rewrite,
  `test_pull_drop_splice.py` for drop's whole-file `unlink`), so only ever
  pass it to a pull apply when every touched file is single-object (or being
  fully rewritten).
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
        """Remove ``object_key``'s source (drop).

        Deletes the file itself only when nothing else would remain
        (`WholeFileSourceWriter` unlinks it unconditionally — see its
        docstring for why that is only safe on single-object files).
        """
        ...


class WholeFileSourceWriter:
    """Blunt: every operation is a whole-file write or delete.

    Correct only when every touched file holds a single object:
    `splice_object` overwrites and `delete_object` unlinks the WHOLE file, so
    on a multi-object file both silently destroy the sibling objects and
    hand-written comments (I6 — the `test_pull_refresh_splice.py` /
    `test_pull_drop_splice.py` regression pair). `hassle pull` uses
    `SplicingSourceWriter` instead.
    """

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


class SplicingSourceWriter(WholeFileSourceWriter):
    """The real (M2 splicer-backed) writer `hassle pull` uses.

    ``refresh`` splices exactly one object's statement in place; ``drop``
    removes exactly one object's statement -- sibling objects and hand-written
    comments in the same file survive byte-for-byte (I6). ``adopt`` (via
    ``write_whole_file``) stays a whole-file write, inherited.

    ``updated_on`` is the ISO date stamped into the splice's ``# hassle:
    updated from UI on <date>`` marker -- a constructor parameter, never read
    from the clock here (R8: no wall-clock in core logic; the CLI edge passes
    today's date, exactly like ``hassle_cli.manifest_io`` stamps `last_synced`).
    """

    def __init__(self, *, updated_on: str) -> None:
        self._updated_on = updated_on

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        from hassle.decompiler.splice import (
            find_object_statement_name,
            merge_missing_imports,
            splice_object,
            split_module_source,
        )

        if not path.exists():
            # Refresh of a file that vanished from the working tree: `content`
            # is a complete decompiled module -- recreate it whole.
            self.write_whole_file(path, content)
            return
        file_source = path.read_text(encoding="utf-8")
        try:
            import_sources, object_sources = split_module_source(content)
            (object_source,) = object_sources
        except ValueError:
            # `content` isn't ONE spliceable object statement plus imports --
            # broken decompiler output. Keep the whole-file behavior so the
            # CLI's post-write compile backstop reports it as a decompiler bug
            # with the file left in place for diagnosis (its documented
            # contract), instead of crashing mid-pull here.
            self.write_whole_file(path, content)
            return

        target_name = find_object_statement_name(file_source, object_key)
        if target_name is None:
            # Stale manifest: the object is tracked against this file but no
            # longer defined in it. Append the refreshed definition -- never
            # clobber what IS in the file (I6).
            marker = f"# hassle: updated from UI on {self._updated_on}\n"
            new_source = (
                file_source.rstrip("\n") + "\n\n\n" + marker + object_source.strip("\n") + "\n"
            )
        else:
            new_source = splice_object(
                file_source,
                object_key=object_key,
                new_source=object_source,
                updated_on=self._updated_on,
            )
        self.write_whole_file(path, merge_missing_imports(new_source, import_sources))

    def delete_object(self, path: Path, object_key: str) -> None:
        from hassle.decompiler.splice import find_object_statement_name, remove_object

        if not path.exists():
            return
        file_source = path.read_text(encoding="utf-8")
        target_name = find_object_statement_name(file_source, object_key)
        if target_name is None:
            # Not defined here (stale manifest) -- nothing to delete; the old
            # whole-file unlink would have destroyed unrelated siblings.
            return
        remaining = remove_object(file_source, object_key=object_key)
        if remaining is None:
            path.unlink()
        else:
            self.write_whole_file(path, remaining)


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
