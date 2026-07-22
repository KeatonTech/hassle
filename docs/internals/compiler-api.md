# Compiler internal API

This is the seam for extending the compiler: adding new trigger/condition
builders, new action verbs, or new control-flow constructs. It covers the
recording-context model, the builder protocols, and how spans attach. It does
**not** cover the frozen IR surface (`docs/internals/ir-format.md`) or the
frozen DSL surface (`docs/internals/dsl-extensions.md`) — those are separate
contracts.

Physical layout (all under `packages/hassle-core/src/`):

| Module | What it is | May you edit it? |
|---|---|---|
| `hassle/` | user-facing import surface (`from hassle import …`) | **Yes**: add new public names to `hassle.__all__` (additions only — see `docs/internals/dsl-extensions.md`) |
| `hassle/compiler/protocols.py` | the three builder protocols | No (implement them) |
| `hassle/compiler/recording.py` | context stack, `record_*`, `when`/`only_if`, option allow-lists | Add new options to the allow-lists; otherwise no |
| `hassle/compiler/builders.py` | the core builders (`state`, `service`, `delay`) — the pattern every sibling module follows | Add sibling builder files; don't rewrite these |
| `hassle/compiler/actions.py` | the action verbs (`service`, `delay`) | Add sibling verb modules |
| `hassle/compiler/bundle.py` | isolated import + compile pipeline + `CompileResult` | No |
| `hassle/compiler/spans.py` | `SourceSpan` + frame capture | No |
| `hassle/ir/normalize.py` | `normalize_ha` | No |

## 1. How a trigger/condition builder registers itself

A trigger builder is **any object with `to_trigger() -> dict`**; a condition builder
has `to_condition() -> dict` (`hassle.compiler.protocols`). Nothing more — no
base class required (they are `runtime_checkable` Protocols).

The user-facing verbs already exist and do the registration for you:

```python
from hassle.compiler.recording import when, only_if
when(my_trigger_builder, another_trigger_builder)   # appends triggers
only_if(my_condition_builder)                        # appends conditions
```

So a new builder family is just: write the builder classes, expose thin
constructor functions (`numeric_state(...)`, `sun(...)`, `on(...)`, `met(...)`),
add those names to `hassle.__all__`. `when`/`only_if` capture the span at the DSL
call site automatically.

**Serialization contract (do this exactly):** emit the **canonical plural HA dict**
directly — `{"trigger": "<type>", ...}` / `{"condition": "<type>", ...}`. Emit
`action:` never `service:`, plural block keys, no legacy singular forms. The
compiler runs `normalize_ha` over the whole object as a backstop, but emitting
canonical form keeps output byte-stable and is required for the goldens.

Dual-purpose builders (like the core `state()`, which is both a trigger via `when`
and a condition via `only_if`) implement **both** `to_trigger` and `to_condition`.

Purpose-specific triggers (`on("motion.detected", target=…, behavior=…, for_=…)`)
and conditions (`met(...)`) are the same pattern: one generic builder that emits the
stored shape (`{"trigger": "<domain.event>", "target": {...}, "behavior": …,
"options": {...}}`). The vocabulary is instance data, validated by the registry, not
hardcoded here.

## 2. How an action / control-flow construct registers itself

A simple action builder has **`to_action() -> dict`** and is recorded by a verb that
calls `record_action`:

```python
from hassle.compiler.recording import record_action
from hassle.compiler.spans import capture_span

def notify(message: str) -> None:
    record_action(MyNotifyAction(message), span=capture_span(depth=0))
```

`record_action` appends to the recorder's **current** action list — which is the top
of the action stack, so nested contexts just work.

### Nested contexts (`if_then` / `choose` / `repeat` / `parallel`)

The recorder exposes `push_actions(target)` for exactly this. A control-flow context
manager records its own container action, then redirects child recording into a
sub-list:

```python
import contextlib
from hassle.compiler.recording import _require_active, RecordedNode
from hassle.compiler.spans import capture_span

@contextlib.contextmanager
def if_then(condition):
    rec = _require_active("if_then")          # the active Recorder
    then_nodes: list[RecordedNode] = []
    # build the shell action now; fill its `then` from then_nodes at exit
    span = capture_span(depth=2)              # skip the CM + contextlib frames
    with rec.push_actions(then_nodes):
        yield
    body = {"if": [condition.to_condition()],
            "then": [n.body for n in then_nodes]}
    rec.current_actions.append(RecordedNode(body, span))
```

Key facts for nesting:

- `Recorder.current_actions` is the live target list; `push_actions(sublist)` makes
  `sublist` current for the duration of the `with`, then pops it. Stacks arbitrarily.
- Record the child actions into a fresh list, then assemble the container `dict`
  (`choose`/`if`/`repeat`/`parallel`) from `[n.body for n in that_list]`.
- **Spans for nested nodes** ride on the `RecordedNode`s in the sub-list; when you
  fold them into the container `body` you keep their `.span` if you also record the
  sub-nodes' spans in the `CompileResult`. `CompileResult.spans_for` returns spans
  tracked per top-level action-list block; extending that to per-nested-node spans
  means widening the span map in `bundle.py` (the one place you may touch the
  pipeline, and it needs a test).

`_require_active(call)` is the internal helper that returns the active recorder or
raises `NoRecordingContextError`; import it from `hassle.compiler.recording`.

### `else_then`

`else_then()` must attach to the immediately-preceding `if`/`choose` action. The
simplest correct implementation inspects `rec.current_actions[-1]` (the just-recorded
`if`/`choose`) and fills its `else`/`default`. Assert it *is* such an action and
raise a what/where/fix error if not (snapshot-test it — see §5).

## 3. How spans attach (and the rule you must not break)

- Every `record_trigger`/`record_condition`/`record_action` captures a `SourceSpan`
  (`file`, `line`) at the DSL call site via `capture_span`. `capture_span(depth=N)`
  walks outward past `N` inner frames, then past all `hassle` (internal) frames,
  to the first user frame. If a helper sits between the DSL call and the record call,
  pass a larger `depth`. For a `@contextlib.contextmanager`-decorated construct,
  `depth=2` skips the generator's own frame and contextlib's trampoline frame,
  landing on the user's `with construct(...):` call site — verified empirically
  and independent of nesting depth (`test_span_depth_empirical.py`).
- Spans live in `CompileResult._spans` (per object, per section) — **never** in the
  IR body. `to_ha()` must stay span-free. There is a test that asserts
  no `.py` path leaks into `to_ha()`; keep it green.

## 4. What you may NOT touch

- **`normalize_ha` and the frozen IR surface** — frozen. If you think you need a
  change, stop and report; update docs/internals/ir-format.md in the same PR or don't do it.
- **The plural canonical schema** — always emit plural + `action:`. No singular keys
  except inside a user's `raw_*` body (which `normalize_ha` handles).
- **`CompileResult.objects` / `spans_for` signatures** — downstream (validation,
  simulator) depends on them.
- **The recording context-var mechanism** — a `ContextVar` stack holds the active
  `Recorder`. Use `when`/`only_if`/`record_action`/`push_actions`; do not reach into
  `_CONTEXT_STACK` directly.

## 5. Error messages

Every user-facing error you add follows *what / where (file:line) / fix*, one
paragraph, and gets a snapshot under `packages/hassle-core/tests/snapshots/errors/`.
Reuse the pattern in `hassle/compiler/errors.py`; capture the span with
`capture_span`. The trap `__bool__` on any runtime expression must raise
`CompileTimeBranchError` (subclass `builders._NoBool`, override `_branch_repr`).

## 6. Scope notes / known simplifications

- The generic action verb is `service("domain.name", **kwargs)`. DESIGN §5.3
  describes the ergonomic `e.light.hallway.turn_on(...)` form; that entity sugar is
  generated by the registry/stub layer and compiles down to the same
  `service(...)` primitive — build on top of it, don't replace it.
- `service(...)` puts bare kwargs into `data`; pass `target=` / `data=` explicitly to
  override. This is HA-valid (HA accepts `entity_id` in `data`).
- `delay(**units)` emits the dict form `{"delay": {minutes: 5}}` (deterministic).
