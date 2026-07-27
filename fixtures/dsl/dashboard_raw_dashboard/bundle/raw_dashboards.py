"""Golden case: `@raw_dashboard` -- the top rung of the raw ladder.

The decorated function returns either the whole §3.2 envelope (`meta` +
`config`) or just a config dict, in which case the decorator's own `url_path=`
supplies the registry metadata. A returned `meta` dict MUST carry `url_path`
(§3.4's identity-sentinel guard) -- otherwise the envelope would silently key
as the DEFAULT dashboard.
"""

from hassle import raw_dashboard


@raw_dashboard(url_path="strategy-one")
def strategy_one():
    return {
        "meta": {
            "url_path": "strategy-one",
            "title": "Strategy",
            "icon": "mdi:auto-fix",
            "show_in_sidebar": True,
        },
        "config": {"strategy": {"type": "original-states"}},
    }


@raw_dashboard(url_path="config-only")
def config_only():
    return {"views": [{"title": "Only a config", "cards": []}]}
