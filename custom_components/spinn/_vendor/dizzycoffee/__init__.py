"""DizzyCoffee — local, app-free control for the Spinn bean-to-cup coffee maker.

This package talks to Spinn's backend with *your* account and *your* machine's
certificate (fetched fresh each session). Nothing in this package publishes to
the machine's command topic; it is read-only by construction. See docs/PROTOCOL.md.
"""

__version__ = "0.1.0"
