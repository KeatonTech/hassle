"""Golden case: DB3c's domain card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/domain.py`: `alarm_panel`,
`area` (an AREA id, not an entity id), `light`, `thermostat`, `humidifier`,
`media_control`, `plant_status`, `todo_list`, `shopping_list` (the legacy
alias -- stays `"shopping-list"`, never upgraded to `todo-list`), and
`weather_forecast`.
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-domain", title="Domain")
def cards_domain():
    with view(title="Domain", type="masonry"):
        c.alarm_panel(
            "alarm_control_panel.home",
            name="Home Alarm",
            states=["arm_home", "arm_away"],
        )
        c.area(
            "living_room",
            navigation_path="/lovelace/living-room",
            show_camera=True,
            display_type="compact",
            alert_classes=["motion", "smoke"],
            sensor_classes=["temperature", "humidity"],
        )
        c.light("light.living_room", name="Living Room", icon="mdi:ceiling-light")
        c.thermostat("climate.living_room", features=[{"type": "climate-hvac-mode-select"}])
        c.humidifier("humidifier.living_room", features=[{"type": "humidifier-toggle"}])
        c.media_control("media_player.living_room")
        c.plant_status("plant.tomato", name="Tomato")
        c.todo_list("todo.groceries", title="Groceries", display_order="alphabetical")
        c.shopping_list(title="Shopping", display_order="alphabetical")
        c.weather_forecast(
            "weather.home",
            show_current=True,
            show_forecast=True,
            forecast_type="daily",
            name="Weather",
        )
