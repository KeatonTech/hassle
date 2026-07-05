"""scripts/movie_time.py — a script under the `scripts/` subdirectory
(DESIGN §5.7/§6)."""

from hassle import script, service


@script(id="movie_time", alias="Movie time", mode="single")
def movie_time():
    service("light.turn_off", entity_id="light.living_room")
    service("cover.close_cover", entity_id="cover.blinds")
