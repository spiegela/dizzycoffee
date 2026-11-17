"""Make the ``dizzycoffee`` client importable inside Home Assistant.

HACS copies only ``custom_components/spinn/``, not the sibling ``dizzycoffee/``
package at the repo root, so the integration ships a verbatim copy of the client
under ``_vendor/dizzycoffee/``. ``ensure_dizzycoffee()`` puts that copy on the
import path — but only as a *fallback*: if a real ``dizzycoffee`` is already
installed (e.g. in a development checkout), it is preferred and the bundled copy
is never used.

The vendored modules only need ``requests`` / ``awsiotsdk`` / ``certifi``, which
are declared in the manifest ``requirements`` and installed by Home Assistant.
"""
from __future__ import annotations

import importlib
import os
import sys

_VENDOR_DIR = os.path.join(os.path.dirname(__file__), "_vendor")


def ensure_dizzycoffee() -> None:
    """Ensure ``import dizzycoffee`` works, falling back to the bundled copy."""
    try:
        importlib.import_module("dizzycoffee")
        return  # a real install (or an earlier bootstrap) already satisfies it
    except ImportError:
        pass
    # Append (not insert) so a genuine install always wins over the bundled copy.
    if _VENDOR_DIR not in sys.path:
        sys.path.append(_VENDOR_DIR)
        importlib.invalidate_caches()
