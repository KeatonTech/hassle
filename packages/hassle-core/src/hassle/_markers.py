"""Comment markers Hassle stamps into bundle source files.

These are plain-text markers, not imports of any layer, so this module must
stay dependency-free: it is shared by ``hassle.compiler`` (which reports on
marked lines in error messages), ``hassle.decompiler.splice`` (which inserts
and strips the marker), and ``hassle.sync.source_writer`` (which appends it
when a UI edit cannot be spliced into a metaprogrammed object).
"""

from __future__ import annotations

#: Stamped above an object definition that was appended (rather than spliced)
#: to carry a UI-side edit. A date follows the prefix on the same line.
UI_SPLICE_MARKER_PREFIX = "# hassle: updated from UI on"
