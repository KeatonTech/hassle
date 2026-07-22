"""Generated agent-facing documentation (DESIGN §12).

Everything here is a pure function of the fixture corpus + `hassle.__all__`
(no filesystem writes) -- the CLI (`hassle-cli`) and `hassle-dev` are
responsible for calling these and writing the result to disk, mirroring the
existing `hassle.registry.stubs` convention (generator lives in
`hassle-core`, wiring lives in the CLI).
"""

from __future__ import annotations
