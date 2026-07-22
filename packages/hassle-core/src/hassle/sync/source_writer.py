"""The frozen `SourceWriter` seam — DESIGN §7.3, §8.3.

`SourceWriter` decouples the sync engine's pull-side (bundle-side) actions from
the LibCST-based splicer. The pull engine (:mod:`hassle.sync.pull`) only
depends on this Protocol. Three implementations:

- `SplicingSourceWriter` — the real one (what `hassle pull` uses): `refresh`
  surgically replaces one object's definition in place and `drop` removes only
  that object's statement, preserving the rest of the file byte-for-byte
  (DESIGN §7.3 test 4, `test_splice_preserves_rest_of_file`), via
  :mod:`hassle.decompiler.splice`.
- `WholeFileSourceWriter` — a blunt, whole-file overwrite. Correct (if not
  surgical) for `adopt` (a brand new file has no "rest of file" to preserve).
  Using it for `refresh`/`drop` on a file holding MORE than one object
  silently clobbers the siblings (the `test_pull_refresh_splice.py`
  regression for refresh's whole-file rewrite, `test_pull_drop_splice.py`
  for drop's whole-file `unlink`), so only ever pass it to a pull apply when
  every touched file is single-object (or being fully rewritten).
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

The CLI owns real conflict UX (rich 3-way DSL diff rendering); this is only
the structured data plumbed through to a human-readable placeholder.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol, runtime_checkable

from hassle._markers import UI_SPLICE_MARKER_PREFIX


@runtime_checkable
class SourceWriter(Protocol):
    """What the pull engine needs to mutate the working tree."""

    def write_whole_file(self, path: Path, content: str) -> None:
        """Create or fully overwrite ``path`` with ``content``."""
        ...

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        """Replace just the definition for ``object_key`` within ``path``.

        `WholeFileSourceWriter` implements this as a whole-file overwrite;
        the real splicer replaces only the matching `def`/decorator block.
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
    hand-written comments (the `test_pull_refresh_splice.py` /
    `test_pull_drop_splice.py` regression pair -- no local or UI edit is ever
    silently lost). `hassle pull` uses `SplicingSourceWriter` instead.
    """

    def write_whole_file(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    def splice_object(self, path: Path, object_key: str, content: str) -> None:
        # This implementation has no LibCST splicer, so it overwrites the
        # whole file. `object_key` is accepted (part of the Protocol) but
        # unused by this implementation.
        del object_key
        self.write_whole_file(path, content)

    def delete_object(self, path: Path, object_key: str) -> None:
        del object_key
        if path.exists():
            path.unlink()


class SplicingSourceWriter(WholeFileSourceWriter):
    """The real (LibCST splicer-backed) writer `hassle pull` uses.

    ``refresh`` splices exactly one object's statement in place; ``drop``
    removes exactly one object's statement -- sibling objects and hand-written
    comments in the same file survive byte-for-byte (no local or UI edit is
    ever silently lost). ``adopt`` (via ``write_whole_file``) stays a
    whole-file write, inherited.

    ``updated_on`` is the ISO date stamped into the splice's ``# hassle:
    updated from UI on <date>`` marker -- a constructor parameter, never read
    from the clock here (no wall-clock in core logic; the CLI edge passes
    today's date, exactly like ``hassle_cli.manifest_io`` stamps `last_synced`).

    ``reconcile_warnings`` (additive): populated when
    ``splice_object`` takes the append path (module docstring: "stale
    manifest... append the refreshed definition") AND the file's CURRENT
    content (before the append) already compiles to an object with this same
    key -- i.e. the object is generated by metaprogramming (a compile-time
    loop) rather than a missing/renamed literal statement, so the append is
    about to create a same-file duplicate the next compile will reject
    (`DuplicateObjectError`, which also names this same reconcile flow when it
    fires). Detected by compiling the file's pre-append source in isolation
    (never the whole bundle -- this writer has no bundle root, only the one
    file being spliced) and checking whether ``object_key`` appears in the
    result; best-effort, deterministic given the same file content (no
    wall-clock, no randomness).
    """

    def __init__(self, *, updated_on: str) -> None:
        self._updated_on = updated_on
        self.reconcile_warnings: list[str] = []

    def _is_metaprogrammed_object(self, file_source: str, object_key: str) -> bool:
        """True if compiling ``file_source`` (the file's content BEFORE the
        append) already produces ``object_key`` -- meaning some compile-time
        construct (typically a `for` loop) generates it, rather than the
        splicer simply failing to find a renamed/moved literal statement."""
        import tempfile

        from hassle.compiler.bundle import compile_bundle

        try:
            with tempfile.TemporaryDirectory() as tmp:
                tmp_file = Path(tmp) / "reconcile_check.py"
                tmp_file.write_text(file_source, encoding="utf-8")
                result = compile_bundle(Path(tmp))
        except Exception:
            # Best-effort diagnostic only -- if the current file doesn't even
            # compile in isolation (e.g. it depends on siblings), that's not
            # this check's problem to report; fall through to "not detected".
            return False
        return object_key in result.objects

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
            # clobber what IS in the file (no local or UI edit is ever
            # silently lost).
            if self._is_metaprogrammed_object(file_source, object_key):
                self.reconcile_warnings.append(
                    f"{object_key} in {path}: this object is generated by metaprogramming "
                    "(a compile-time loop) -- the UI edit was appended under a `# hassle: "
                    "updated from UI on <date>` marker rather than spliced into the loop, "
                    "since there is no single literal statement to replace. Reconcile by "
                    "hand -- fold the appended block into the loop, extract this object out "
                    "of the loop, or delete the appended block -- then re-run `hassle "
                    "validate` (the bundle will not compile until the duplicate id is "
                    "resolved)."
                )
            marker = f"{UI_SPLICE_MARKER_PREFIX} {self._updated_on}\n"
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
