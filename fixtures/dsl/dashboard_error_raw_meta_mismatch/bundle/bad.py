"""Error case: a returned `meta.url_path` contradicting the decorator's.

A dashboard has exactly ONE identity. Two disagreeing spellings would register
the object under one and push it to the other.
"""

from hassle import raw_dashboard


@raw_dashboard(url_path="declared-one")
def mismatched():
    return {
        "meta": {"url_path": "other-one", "title": "Mismatched"},
        "config": {"views": []},
    }
