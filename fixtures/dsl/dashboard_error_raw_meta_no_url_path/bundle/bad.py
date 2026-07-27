"""Error case: a `@raw_dashboard` body returns `meta` without a `url_path`.

§3.4's identity-sentinel guard: at the IR layer such a `meta` falls through to
the `default` sentinel, which would silently key a malformed dashboard as THE
default dashboard. The compile path rejects it loudly instead.
"""

from hassle import raw_dashboard


@raw_dashboard(url_path="lost-identity")
def lost_identity():
    return {
        "meta": {"title": "Lost", "show_in_sidebar": True},
        "config": {"views": []},
    }
