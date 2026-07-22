# Compiler internals

Design rationale that's too long to keep inline in the source. See DESIGN.md for the
user-facing DSL semantics; this file is for maintainers of `hassle.compiler`.

## Shared-script parameters are bound to runtime markers, not their Python defaults

When the compiler invokes a `@shared_script`-decorated function to build its action
sequence, every parameter whose name matches a declared field is bound to a
`param(name)` marker rather than to whatever default the `def` line declares. So inside
the body, `tag=tag` means exactly `tag=param("tag")` — the parameter is Jinja text under
construction (`{{ tag }}`), not a real string/int/bool, until it renders inside Home
Assistant.

An earlier design considered a `param_default(name)` helper that would return the
field's compile-time default so things like `range(param_default("times"))` could work
naturally in the body. This was rejected: it would silently ignore whatever the caller
actually passed at runtime, since the compiler only invokes the body once (with the
default) to build the static sequence. The HA-side field would exist but be a lie — the
UI would show it as configurable, but changing it would do nothing. The rule instead: a
genuinely runtime count belongs in `with repeat_count(times):` (HA's native runtime
repeat — accepts the marker directly and renders `{"count": "{{ times }}"}`, honoring
the caller); a genuinely runtime iteration belongs in `with repeat_for_each(items):`; a
genuinely runtime membership/length check belongs in a runtime condition/template
(`.eq()`/`.in_()`/`template(...)`) evaluated inside Home Assistant; a genuinely
compile-time value was never an honest HA field to begin with, and belongs in a
module-level constant or a `@macro` argument instead.

Because a bound parameter is a `str` subclass (`TemplateExpr`), ordinary Python misuse
(`range(times)`, `if tag:`, `int(times)`, `for x in items:`, `"a" in tag`, `len(tag)`,
`tag[0]`) would otherwise silently do the wrong thing — iterate/index/measure the
literal `"{{ name }}"` text — instead of raising. `_BoundParamMarker` traps the relevant
dunders and raises `SharedScriptParamMisuseError`, which names the honest runtime or
compile-time alternative depending on what the misuse was trying to do. The container
dunders (`__iter__`, `__contains__`, `__len__`, `__getitem__`) are trapped only on this
bound marker; the same trap does not exist yet on a plain `TemplateExpr`/`param()`
result used outside a shared-script body, which is a pre-existing gap, not something
introduced here.

`__str__`/`__repr__`/`_as_operand`/composition (`+`, `.eq()`, `concat(...)`, ...) are
deliberately not trapped — string rendering and the whole template-builder operator
surface must keep working exactly like a plain `TemplateExpr`. No internal
codegen/rendering path calls `len()`/`iter()`/`in`/indexing on a compiler-side template
value; every consumer goes through `str()`/`.to_template()`/`._as_operand()`.

## `field_default()`

A shared-script body's own parameters are always runtime template markers inside the
body (see above), regardless of the parameter's declared Python default. That means the
body-true annotation for any field is `TemplateExpr`, so the whole composable
expression surface (`tag.eq(...)`, `sun_angle / 2`, `concat(tag, ...)`) type-checks —
otherwise pyright would infer a plain `str`/`int`/`float` from the default and let
something like `sun_angle: int` make `sun_angle / 2` type-check as real division, when
it actually builds a Jinja expression.

Plainly declaring `tag: TemplateExpr = ""` doesn't type-check (`""` is not a
`TemplateExpr`). `field_default(value)` is the identity function at runtime — it
returns `value` completely unchanged, so `inspect.signature(...).parameters[...].default`
(what the generated HA `fields` block actually reads) sees the real declared default,
e.g. plain `""` or plain `0` — but it's typed as returning `TemplateExpr`, so the
default expression type-checks against the parameter's `TemplateExpr` annotation.

The decorated function's caller-side wrapper has signature `(*args: Any, **kwargs:
Any) -> None`, fully decoupled from the body's own annotations, so this helper has no
effect on call-site typing either way.

## Recompile shape for shared-script fields

When `@shared_script(fields=...)` is given explicitly, it's stored verbatim as the
script's `fields` block instead of the signature-derived one, since a real,
UI-authored script can carry field metadata (`name`/`description`/`selector`/...) that
a Python signature alone can't reconstruct. `fields=`'s keys then become the source of
truth both for call-site keyword validation and for which names `param()` may
reference — not just the ones that happen to also be Python parameters.
