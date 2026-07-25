# Project history

Hassle was built in 2026 as a test-first, milestone-driven project implemented
largely by AI coding agents working in parallel against a written plan. The
documents in this directory are that record, preserved as written (apart from
anonymizing the author's home setup). They are **not** current guidance — the
rules that still bind development live in [CONTRIBUTING.md](../../CONTRIBUTING.md),
and the living design doc is [DESIGN.md](../../DESIGN.md) — but they explain
*why* the codebase looks the way it does, and the test contracts they define
are still the suite you run today.

- [milestones.md](milestones.md) — the implementation plan: milestone-by-
  milestone deliverables, the "write these tests first" acceptance contracts,
  and the amendments made along the way.
- [acceptance-runs.md](acceptance-runs.md) — logs from the doc-quality
  acceptance harness (`hassle-dev acceptance`), which evaluated how well a
  code-generation model could complete tasks using only the generated docs.

## Legend

The record uses internal shorthand. Decoder ring:

| Term | Meaning |
|---|---|
| **M0 – M21** (also `M1.1`, `M7.1`, `M0.V`) | Milestone numbers from the plan in [milestones.md](milestones.md). `M0.V` was the live-HA API-verification track. |
| **"Write these tests first" / "test N"** | Each milestone's acceptance contract: numbered tests committed (failing) before implementation. |
| **"done gate"** | A milestone's final acceptance demonstration — an end-to-end test proving the milestone's goal. |
| **R1 – R8** | The global engineering rules. Still in force; restated for contributors in [CONTRIBUTING.md](../../CONTRIBUTING.md). |
| **I1 – I6** | The design invariants ([DESIGN.md](../../DESIGN.md) §2) — e.g. I3 is `compile(decompile(x)) == x`, I6 is "no edit is silently lost". |
| **F1 – F3** | Interface freeze points that let workstreams run in parallel: F1 the IR schema (now [docs/internals/ir-format.md](../internals/ir-format.md)), F2 the Backend/plan seam (now [docs/internals/backend-protocol.md](../internals/backend-protocol.md)), F3 the top-level DSL surface (now [docs/internals/dsl-extensions.md](../internals/dsl-extensions.md)). |
| **G1 – G12** | The product goals table (DESIGN.md §1). |
| **"workstream"** | One of the parallel implementation tracks (e.g. triggers/conditions vs. actions/control-flow) that shared only frozen interfaces. |
| **"work item A/B"** | Sub-tasks within a milestone. |
| **"polish batch"** | A numbered list of small cleanups executed after a milestone landed. |
| **task #NN / PR #NN** | Numbers from the internal task tracker / the repository's own pull requests. |
| **"reviewer finding B1/N2…"** | Numbered findings from the review agent's pass on a milestone PR (B = blocking, N = non-blocking). |
| **"CI round N" / "residue-coverage round N"** | Iterations of CI-driven fixing; residue rounds were decompiler-coverage hardening passes against a real HA export. |
| **"owner"** | The project author, who made the binding product decisions recorded here. |
| **"field report"** | A bug report from the author's own live deployment — the first real installation (its entity names appear in fixtures anonymized to the "kai" persona). |
| **coordinator / implementer / reviewer / fixture-wrangler** | The agent roles: an orchestrating session, milestone implementers, a review agent, and a fixtures/boilerplate agent. |
| **`ux/<topic>`, `fix/<topic>`, `m<N>/<topic>`** | Branch-naming conventions for DSL-ergonomics work, bug fixes, and milestone work respectively. |
| **§N references** | Sections of DESIGN.md (design) or [docs/internals/ha-api-notes.md](../internals/ha-api-notes.md) (empirical HA API findings, still a living reference). |
