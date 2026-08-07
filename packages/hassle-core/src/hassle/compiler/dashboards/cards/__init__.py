"""Card-builder families (F5, docs/internals/dashboards-design.md §6.1.1).

One module per DB3 batch. Each module registers its own :class:`CardSpec` rows
into ``hassle.compiler.dashboards.card_registry.CARD_REGISTRY`` at import
time; the public re-export point is ``hassle/cards.py``, which imports each
family module directly. This package has no re-exports of its own, so this
file stays an append-only list of one-line notes as batches land, never
growing real code of its own:

- ``layout`` (DB3a) -- vertical-stack, horizontal-stack, grid, conditional,
  entity-filter (the container cards).
- ``display`` (DB3a) -- entities, glance, tile, entity, button, heading.
- ``visual`` (DB3b) -- gauge, history-graph, statistics-graph, sensor,
  statistic, markdown, clock, calendar, logbook.
- ``media`` (DB3b) -- iframe, picture, picture-glance, picture-elements, map.
- ``domain`` (DB3c) -- alarm-panel, area, light, thermostat, humidifier,
  media-control, plant-status, todo-list, shopping-list (legacy alias),
  weather-forecast.
- ``energy`` (DB3c) -- the 12 Energy dashboard cards: energy-date-selection,
  energy-usage-graph, energy-solar-graph, energy-gas-graph,
  energy-water-graph, energy-distribution, energy-sources-table,
  energy-grid-neutrality-gauge, energy-solar-consumed-gauge,
  energy-carbon-consumed-gauge, energy-self-sufficiency-gauge,
  energy-sankey.
"""

from __future__ import annotations
