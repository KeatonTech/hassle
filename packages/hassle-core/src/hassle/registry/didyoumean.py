"""A small Levenshtein-distance "did you mean?" helper.

No third-party dependency: a plain O(n*m) dynamic-programming edit distance is
plenty fast for the short strings (entity ids, area/floor/label ids) this is
used on.
"""

from __future__ import annotations


def levenshtein(a: str, b: str) -> int:
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        curr = [i] + [0] * len(b)
        for j, cb in enumerate(b, start=1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                prev[j] + 1,  # deletion
                curr[j - 1] + 1,  # insertion
                prev[j - 1] + cost,  # substitution
            )
        prev = curr
    return prev[-1]


def did_you_mean(
    candidate: str, known: set[str] | list[str], *, max_distance: int = 3
) -> str | None:
    """Return the closest match to ``candidate`` in ``known``, or ``None``.

    A relative threshold (roughly a quarter of the candidate's length, floor 1,
    capped by ``max_distance``) keeps short strings from matching wildly
    different short strings while still catching realistic typos on longer ids.
    """
    if not candidate:
        return None
    threshold = min(max_distance, max(1, len(candidate) // 3))
    best: str | None = None
    best_distance = threshold + 1
    for k in known:
        d = levenshtein(candidate, k)
        if d < best_distance:
            best = k
            best_distance = d
    if best is not None and best_distance <= threshold:
        return best
    return None
