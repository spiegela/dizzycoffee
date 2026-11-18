"""Parse the account's usage stats (``GET stats/api/user-stats``).

Shape (live-captured, docs/PROTOCOL.md §3)::

    {"servings_count": 2137, "updated_at": "...",
     "stats": {"<recipe id>": {"id", "name", "slug", "type", "recipe_count", "host_version"}, ...}}

``servings_count`` is the sum of every recipe's ``recipe_count``. The stats are
per Spinn account, not per machine. Pure functions; no I/O.
"""
from __future__ import annotations

from typing import Any


def _int(val: Any) -> int | None:
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def parse_user_stats(body: Any) -> dict[str, Any] | None:
    """Slim the user-stats response for Home Assistant.

    Returns ``{"servings", "updated_at", "top_recipe", "recipes"}`` where
    ``recipes`` is ``[{"name", "slug", "type", "count"}, ...]``, most brewed
    first. ``None`` if the body isn't the expected shape.
    """
    if not isinstance(body, dict):
        return None
    per_recipe = body.get("stats")
    recipes: list[dict[str, Any]] = []
    if isinstance(per_recipe, dict):
        for rec in per_recipe.values():
            if not isinstance(rec, dict):
                continue
            count = _int(rec.get("recipe_count"))
            if count is None:
                continue
            recipes.append(
                {
                    "name": rec.get("name"),
                    "slug": rec.get("slug"),
                    "type": rec.get("type"),
                    "count": count,
                }
            )
    recipes.sort(key=lambda r: (-r["count"], str(r["name"] or "")))
    servings = _int(body.get("servings_count"))
    if servings is None and recipes:
        servings = sum(r["count"] for r in recipes)
    if servings is None:
        return None
    return {
        "servings": servings,
        "updated_at": body.get("updated_at"),
        "top_recipe": recipes[0]["name"] if recipes else None,
        "recipes": recipes,
    }
