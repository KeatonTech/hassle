# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

The three distributions in this repository (`hassle-core`, `hassle-cli`,
`hassle-dev`) are versioned together.

## [Unreleased]

## [0.1.0] — 2026-07-22

First public release. Everything below is the initial feature set rather than
a delta from a previous version.

### Added

- **Python DSL** for Home Assistant automations, scripts, and the nine
  storage-collection helper domains, compiling to the exact JSON Home
  Assistant's own UI writes. Typed builders for every classic trigger and
  condition, the 2026.7+ purpose-based triggers, full control flow
  (`if`/`choose`/`repeat`/`parallel`/`wait`), a typed Jinja expression builder
  with math and datetime helpers, and blueprint automations.
- **Reusable logic**: `@macro` (inlined at compile time) and `@shared_script`
  (compiles to a real Home Assistant script with typed fields).
- **`raw_*` escape hatch** so any config Home Assistant can store round-trips
  losslessly, even when the typed surface can't express it.
- **Two-way sync**: `hassle pull` merges UI-side edits into local source via a
  LibCST splicer that preserves your formatting and comments; `hassle push`
  computes a three-way plan against a committed `manifest.lock` baseline,
  re-verifies hashes immediately before writing, and rolls back on failure.
  Conflicts are surfaced, never silently resolved.
- **Deterministic simulator** (`hassle test`) with a fake clock and no network
  or real devices, so automations can be unit-tested in milliseconds.
- **Validation** (`hassle validate`): compile errors, entity/service/area/label
  reference checks with did-you-mean suggestions, and Jinja linting. `--json`
  output is the editor-integration contract.
- **Generated typed stubs** (`.pyi`) from a registry snapshot, giving editors
  autocompletion and typo detection with no extension required.
- **Generated per-bundle docs** (`AGENTS.md`, `docs/DSL.md`, `docs/COOKBOOK.md`)
  regenerated on every `init`/`pull`.
- **CLI**: `init`, `login`, `pull`, `status`, `plan`, `push`, `validate`,
  `test`, `run` (simulator or `--live`), `explain`, `render`, `stubs`, `fmt`,
  `doctor`.
- **VS Code extension** (unpublished; install from source) adding Problems-pane
  diagnostics and a compiled-YAML panel.
- MIT license, `CONTRIBUTING.md`, and `SECURITY.md`.

### Security

A pre-release audit hardened the boundary between Home Assistant and the
local machine. Since there was no prior release, these are hardening notes
rather than fixes to a shipped version:

- Config fetched from HA can never reach generated bundle source outside a
  literal position. Values render through `repr`; stored field names that
  aren't safe Python identifiers route into `**{...}` literals instead of
  identifier positions. Previously a crafted blueprint path, helper/script
  field name, or service-call data key could inject Python that `hassle pull`
  then executed during its own pre-write self-check.
- The simulator renders templates in `jinja2.sandbox.SandboxedEnvironment`,
  matching Home Assistant's own posture, so a template stored in HA cannot
  reach Python builtins during `hassle test`.
- `hassle pull` refuses to write through a symlink or to any path resolving
  outside the bundle root, and resolves relative destinations against the
  bundle root rather than the process working directory.
- Strings supplied by HA are stripped of terminal control sequences before
  being printed.
- `hassle login` prompts for the token with hidden input instead of requiring
  it in `argv`; `hassle doctor`'s secret scan recurses the bundle and detects
  JWT-shaped literals, key-name variants, and URL-embedded credentials; and
  the CLI warns when the HA URL is plain HTTP to a non-private address.
- Workflows declare `permissions: contents: read`, as does the CI workflow
  scaffolded into new bundles.

[Unreleased]: https://github.com/KeatonTech/hassle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/KeatonTech/hassle/releases/tag/v0.1.0
