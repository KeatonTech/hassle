"""Error case: `@raw_dashboard(default=True)` returning a non-null `meta`.

THE default dashboard has no dashboard-registry item, so there is nowhere for
`meta` to be written. The message must talk about the RETURNED DICT's `meta`
key -- not about `@dashboard(...)` keywords the author never wrote.
"""

from hassle import raw_dashboard


@raw_dashboard(default=True)
def default_with_meta():
    return {
        "meta": {"url_path": "not-allowed", "title": "Nope"},
        "config": {"views": []},
    }
