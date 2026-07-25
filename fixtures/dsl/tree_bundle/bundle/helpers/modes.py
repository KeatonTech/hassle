"""helpers/modes.py — declarative; synced like any object; referenced by import
elsewhere in the tree (DESIGN §5.3/§5.7). Exercises the bundle loader recursing
into subdirectory packages."""

from hassle import input_boolean

guest_mode = input_boolean(id="guest_mode", name="Guest Mode", icon="mdi:account")
