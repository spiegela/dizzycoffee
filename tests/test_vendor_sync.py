"""The bundled client under _vendor/ must match the real one at the repo root.

HACS / Marketplace installs only get custom_components/spinn/, so they run the
bundled copy. If this fails, re-sync it (see custom_components/spinn/_vendor/README.md):

    cp dizzycoffee/{__init__,api,connection,commands,recipes}.py \\
       custom_components/spinn/_vendor/dizzycoffee/
"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REAL = ROOT / "dizzycoffee"
VENDOR = ROOT / "custom_components" / "spinn" / "_vendor" / "dizzycoffee"
BUNDLED = ("__init__.py", "api.py", "connection.py", "commands.py", "recipes.py")


@pytest.mark.parametrize("name", BUNDLED)
def test_bundled_module_matches(name: str) -> None:
    assert (VENDOR / name).read_bytes() == (REAL / name).read_bytes(), (
        f"_vendor/dizzycoffee/{name} differs from dizzycoffee/{name}; re-sync the bundled copy"
    )


def test_no_unexpected_bundled_modules() -> None:
    assert sorted(p.name for p in VENDOR.glob("*.py")) == sorted(BUNDLED)
