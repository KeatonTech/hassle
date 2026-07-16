# hassle-core

The library behind everything: the DSL, the compiler/decompiler, the sync
engine, the Home Assistant backends, and the deterministic simulator. The
distribution is named `hassle-core`; it installs a single import package,
`hassle` (internals are subpackages, never sibling packages).

The `hassle` CLI (`packages/hassle-cli`) is a thin command layer over this
package. If logic could ever be needed by another frontend (an editor
extension, a bot, a different CLI), it belongs here, not in the CLI.

## Layout

Dependencies flow strictly downward — a lower layer never imports an upper one:

| Subpackage | What it is |
|---|---|
| `hassle.ir` | The frozen intermediate representation: pydantic models for automations/scripts/helpers, canonical JSON hashing, HA-shape normalization, object keys/slugs. Imports nothing else in the package. |
| `hassle.compiler` | DSL → IR. The typed builder surface (`when`, `only_if`, `service`, control flow, templates, math expressions, macros, shared scripts, helper declarations) and the bundle compiler. The public DSL surface is re-exported at the top level (`hassle.__all__`) and is a compatibility contract. |
| `hassle.decompiler` | IR → DSL. Code generation for pulled objects, LibCST-based splicing of UI edits into existing source files, Jinja template inversion, and decompile-coverage accounting. |
| `hassle.backend` | Talking to Home Assistant: the real REST/WebSocket backend (`direct`), an in-memory `FakeBackend` with the same observable behavior for unit tests, version checks, and the (stub) mirror. |
| `hassle.registry` | The registry snapshot (entities/services/areas/labels/devices), reference validation with did-you-mean findings, and generated `.pyi` stubs for editor autocompletion. |
| `hassle.sync` | The three-way plan (bundle ↔ manifest ↔ live HA), the push apply engine with rollback, the decompiler-backed pull engine (`pull_apply`), and the `SourceWriter` seam that keeps file writing pluggable. |
| `hassle.testing` | The public simulator surface bundles use in their `tests/` (a pytest plugin provides the `sim` fixture): fake clock, trigger firing, service-call capture. Tests execute compiled IR, never DSL Python directly. |
| `hassle.docs` | Generators for the agent-facing docs a bundle carries (`AGENTS.md`, `docs/DSL.md`, `docs/COOKBOOK.md`). |

Two deliberate wrinkles in the layering:

- `hassle.registry` imports `hassle.compiler` (not the other way around): the
  registry's generated entity accessors are DSL objects, so the entity
  reference type lives with the DSL.
- `hassle._markers` is a dependency-free leaf module for source-file comment
  markers shared by compiler, decompiler, and sync.

## In scope

- Everything needed to compile, decompile, validate, plan, apply, and simulate
  a bundle — with no UI/terminal concerns.
- Invariants this package must never break:
  - every HA write goes through the same config APIs the HA frontend uses;
  - an existing object's HA `id` is never changed;
  - `compile(decompile(x)) == x` for any config — unrepresentable shapes use
    the `raw_*` escape hatch rather than dropping data;
  - no local or UI edit is ever silently lost — conflicts are surfaced;
  - deterministic output: no wall clock, no randomness in core logic.

## Out of scope

- Terminal UX, argument parsing, keyring/token storage, git operations,
  scaffolding of new bundles — all `hassle-cli`.
- Repo-internal development tooling (golden regeneration, corpus stats, docs
  gates) — `hassle-dev`.
- Anything that writes YAML files behind HA's back — out of scope everywhere,
  by design.

## Conventions

- `pyright --strict` applies to this package's `src/` and is enforced in CI.
- Unit tests never touch the network; `FakeBackend` stands in for HA. Tests
  marked `integration` (under `tests/integration/`) are the only exception.
- Error messages are product surface: state what happened, where
  (`file:line`), and how to fix it, in one paragraph — and they are
  snapshot-tested.

Deeper design notes live in `docs/internals/` and `DESIGN.md` at the repo
root.
