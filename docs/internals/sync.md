# Sync internals

Design rationale that's too long to keep inline in the source. See docs/internals/backend-protocol.md for the
frozen plan/apply data model and DESIGN.md §8 for the user-facing sync semantics; this file
is for maintainers of `hassle.sync`.

## Pull-side apply: real decompiled source, not a placeholder

`hassle.sync.pull.apply_pull` uses a JSON-comment placeholder for `refresh`/`adopt` content —
it's explicitly documented as a stand-in for a real `SourceWriter` implementation.
`hassle.sync.pull_apply` is that real implementation: it re-implements `apply_pull`'s action
dispatch, but with real decompiled DSL source (`hassle.decompiler.decompile_bundle`) instead
of the placeholder, while keeping the exact same conflict-marker format (docs/internals/backend-protocol.md's
`<<<<<<< local` block) so a conflict written by the CLI looks identical to one written by
`RecordingSourceWriter`-based unit tests.

### Cross-file script-call rewrite during pull apply

A caller action `{"action": "script.<id>", ...}` decompiles to a real function call (with a
`from <module> import <fn>` when the callee lives in a different destination file) when
`<id>` is a MANAGED script elsewhere in the same pull batch — built once per
`apply_pull_with_decompiler` call from every REFRESH/ADOPT entry's script bodies
(`hassle_cli.bundle_ops.build_script_refs`) and threaded into every `decompile_bundle` call.

Only the ADOPT batches' WHOLE-FILE writes can safely gain a new top-level import line this
way; `_refresh`'s LibCST splice (`hassle.decompiler.splice.splice_object`) replaces exactly
one top-level statement and cannot inject a new import alongside it — a refreshed object
calling a CROSS-FILE script therefore stays `service()` there (never `raw`, no data lost,
just not rewritten on that particular code path). A same-batch call within the same splice
never arises, since a splice always targets exactly one object.

### Why the adopt-batch self-check is batch-level, not per-file

Before any ADOPT destination is written, `apply_pull_with_decompiler` materializes EVERY
adopt batch's decompiled output together into one isolated temp directory (same relative
destination paths as the real bundle) and compiles that whole tree once, rather than
checking each file in isolation. Checking files in isolation was tried first and rejected:
it false-positives on the ordinary, correct case of a script and a cross-file caller BOTH
being freshly adopted in the same pull — their destination files are siblings, but each is
meaningless compiled alone (`ModuleNotFoundError` on the sibling's own import, not a real
bug). Compiling the whole adopted-file set together resolves cross-file imports exactly like
the real bundle would, while still being strictly cheaper and more precise than the
CLI-level whole-bundle backstop: it fires BEFORE any file is written or the manifest is
touched, and `DecompiledBatchDoesNotCompileError` names every destination path involved.

This is **not** extended to `_refresh`'s single-object splice: a spliced object's rewritten
call may target a script living in a file this pull isn't touching at all (no ADOPT/REFRESH
entry for it), whose real on-disk content isn't available to materialize here — the
CLI-level whole-bundle backstop (`hassle_cli.cli.pull`, which runs after every write,
`_refresh` included) is the correct and sufficient backstop for that path.

### Why the self-check compares canonical JSON values, not decompiled text

The self-check doesn't just assert that freshly decompiled source *compiles without
raising* — that alone isn't the same thing as `compile(decompile(x)) == x`. A concrete case
that slipped through a compiles-without-raising check: a `repeat.for_each` template STRING
that a (now-fixed) decompiler/compiler bug silently exploded into a list of individual
characters compiled just fine (`list("...")` never raises), so a clean compile let a wrong
value through to disk.

The fix recompiles every adopted/refreshed object and compares it against the ORIGINAL
stored `remote` config it was decompiled from; `DecompiledValueMismatchError` is raised for
a value mismatch too, not just a raised exception.

The first attempt at this value comparison decompiled BOTH the recompiled object and the
original stored config to DSL source and compared the TEXT (the same technique
`hassle_cli.diffing.is_modernization_only_diff` uses on the plan side) — that was wrong,
because decompiled TEXT is not context-free. The SAME IR value can decompile to different
Python source depending on what ELSE is being decompiled alongside it in a real multi-object
batch: a sibling object's alias colliding forces a `_2` function-name suffix (DESIGN §7.3's
deterministic dedup), and a same-batch script call resolves through a `CallResolver` to a
real function call instead of `service(...)`. Neither of those is a value change (a Python
identifier and a call-site rewrite are never part of `to_ha()`), but a text comparison sees
them as "different DSL" and raises anyway — a false positive across an entire adopt batch,
since one mismatched object aborted the write of every sibling in the same self-check call,
including helpers that were never actually wrong.

The fix compares canonical-JSON VALUES, never decompiled text:
`hassle.ir.modernize.modernize_for_comparison` is the bounded, deterministic transform a
decompile+recompile cycle is expected to apply (inner `platform:` -> `trigger:`, and a
string/numeric `delay:` -> the dict-of-units form; nothing else), applied to `original`
before hashing and comparing against `recompiled.to_ha()`. This is CONTEXT-FREE by
construction: it only ever looks at the JSON value itself, so the same input always
modernizes to the same output regardless of what else is being compiled/decompiled
alongside it in a batch.
