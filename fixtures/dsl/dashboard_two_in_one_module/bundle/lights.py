"""Golden case: two dashboards declared in ONE module.

The per-file default (`dashboards/<module_name>.py`) is a placement default,
never a rule: the compiler imposes no file discipline, so any number of
dashboards may share one file (docs/internals/dashboards-design.md §7).
"""

from hassle import dashboard, raw_card, section, view


@dashboard(url_path="upstairs-lights", title="Upstairs")
def upstairs():
    with view(title="Upstairs", path="upstairs"), section():
        raw_card({"type": "light", "entity": "light.bedroom"})


@dashboard(url_path="downstairs-lights", title="Downstairs")
def downstairs():
    with view(title="Downstairs", path="downstairs"), section():
        raw_card({"type": "light", "entity": "light.hall"})
