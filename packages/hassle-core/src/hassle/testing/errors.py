"""Simulator-surface errors (what / where / fix, one paragraph, snapshot-tested)."""

from __future__ import annotations


class UnsupportedTemplateError(Exception):
    """A Jinja template used a construct outside the simulator's supported subset.

    DESIGN §10.1: the simulator implements real jinja2 plus HA's most-used
    extension functions/filters and math set -- never silently wrong. Anything
    else (an unregistered HA integration helper, template syntax errors, …)
    raises this, naming the offending construct and pointing at
    ``hassle render --live`` (which renders against the real instance instead).
    """

    def __init__(self, construct: str, template_text: str, *, reason: str | None = None) -> None:
        self.construct = construct
        self.template_text = template_text
        detail = f" ({reason})" if reason else ""
        super().__init__(
            f"Template `{template_text}` uses `{construct}`{detail}, which the local "
            f"simulator does not implement -- it supports real Jinja2 plus HA's most-used "
            f"extension functions/filters and math set, not the full HA template "
            f"environment. Fix: simplify the template to the supported subset, or verify "
            f"it against the real instance with `hassle render --live` instead of the "
            f"simulator."
        )


class ScriptRecursionError(Exception):
    """Script-call expansion exceeded the nesting cap.

    A direct ``script.<slug>`` call runs the callee inline (blocking, like
    real HA); scripts calling each other in a cycle would otherwise expand
    forever.
    """

    def __init__(self, slug: str, max_depth: int) -> None:
        self.slug = slug
        self.max_depth = max_depth
        super().__init__(
            f"Simulating this run expanded nested script calls more than {max_depth} "
            f"levels deep (last callee: `script.{slug}`) -- almost certainly scripts "
            f"calling each other in a cycle (recursion), which would never terminate in "
            f"real HA either. Fix: break the cycle so no script (transitively) calls "
            f"itself, or restructure the shared logic into one script both callers use."
        )
