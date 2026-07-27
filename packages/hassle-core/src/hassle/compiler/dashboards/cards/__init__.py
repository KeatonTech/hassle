"""One module per DB3 card-builder batch (docs/internals/dashboards-design.md
§6.1.1, freeze F5): ``layout``, ``visual``, ``media``, ``domain``, ``energy``, …

This package has no re-exports of its own -- ``hassle/cards.py`` imports each
family module directly (its "builder registration point" comment block) --
so this file stays an append-only list of one-line docstring notes as
batches land, never growing real code of its own.

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
