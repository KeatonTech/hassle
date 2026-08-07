"""Golden case: DB3b's media card family (§5.3, §6.1.1).

One usage of every `hassle.cards` builder in `cards/media.py`: `iframe`,
`picture`, `picture_glance`, `picture_elements` (with an `elements=`
passthrough list, §5.3's "passthrough-in-v1" sub-vocabulary), `map` (with
`geo_location_sources=`).
"""

from hassle import cards as c
from hassle import dashboard, view


@dashboard(url_path="cards-media", title="Media")
def cards_media():
    with view(title="Media", type="masonry"):
        c.iframe(
            "https://example.com/panel",
            title="Panel",
            aspect_ratio="75%",
        )
        c.picture(
            "/local/floorplan.png",
            tap_action={"action": "navigate", "navigation_path": "/lovelace/floorplan"},
        )
        c.picture_glance(
            "light.hall",
            "lock.front_door",
            title="Entry",
            image="/local/entry.jpg",
            camera_image="camera.front_door",
        )
        c.picture_elements(
            "/local/floorplan.png",
            camera_image="camera.front_door",
            elements=[
                {
                    "type": "state-icon",
                    "entity": "light.hall",
                    "style": {"top": "20%", "left": "30%"},
                },
                {"type": "state-label", "entity": "sensor.cpu_temp"},
            ],
        )
        c.map(
            "device_tracker.phone",
            "person.alex",
            geo_location_sources=["all"],
            hours_to_show=6,
        )
