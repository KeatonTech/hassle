"""Card-builder families (F5, docs/internals/dashboards-design.md §6.1.1).

One module per DB3 batch: ``layout`` (containers — DB3a), ``display`` (leaf
cards — DB3a), and further batches (``visual``, ``domain``, ...) added by
sibling workstreams. Each module registers its own :class:`CardSpec` rows into
``hassle.compiler.dashboards.card_registry.CARD_REGISTRY`` at import time.

This ``__init__.py`` intentionally stays empty (append-only in spirit, but
nothing needs appending): the public re-export point is ``hassle/cards.py``,
which imports each family module directly
(``from hassle.compiler.dashboards.cards.layout import ...``).
"""

from __future__ import annotations
