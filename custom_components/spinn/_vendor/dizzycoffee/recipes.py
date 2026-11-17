"""Recipe catalog + slider maths (pure functions, no I/O).

A Spinn recipe is edited only through its ``slider`` ranges; the server derives
every brewer parameter from three 0..1 positions (docs/PROTOCOL.md §3):

* ``coffee_strength_float`` = (coffee_weight - min) / (max - min)
  over ``slider.coffee_weight`` (0.1 g units; 140 = 14 g)
* ``water_level_float``     = (drink_size / shots - min) / (max - min)
  over ``slider.volume_extraction`` (ml per shot)
* ``water_balance_float``   = (pct - min) / (max - min)
  over ``slider.water_balance`` (%; Americano-style recipes only)

plus ``coffee_order`` (0 = coffee first, 1 = water first) where the slider allows it.
These helpers convert between those and human units (grams, ml, %).
"""
from __future__ import annotations

from typing import Any

# Cookbook slot layout (0-based brew byte) — see docs/PROTOCOL.md §3.
SLOT_ROLES = {0: "user1", 1: "user2", 2: "user3", 3: "user4",
              4: "tall", 5: "medium", 6: "small", 7: "temp"}
BREWABLE_SLOTS = range(0, 7)
TEMP_SLOT = 7

# The app hard-codes its milk drinks as a ristretto shot plus frothing steps
# (RecipesRepository.milkRecipes); they have no server record. Descriptions here
# are our own wording.
MILK_BASE_SLUG = "ristretto"
MILK_GUIDES: list[dict[str, Any]] = [
    {"id": "milk-latte", "name": "Latte", "slug": "milk-latte",
     "note": "A ristretto shot under 6–8 oz of steamed milk with a thin layer of foam.",
     "items": ["6–8 oz milk", "Ristretto shot", "Milk frother"]},
    {"id": "milk-cappuccino", "name": "Cappuccino", "slug": "milk-cappuccino",
     "note": "A ristretto shot with equal parts hot milk and thick foam.",
     "items": ["4 oz milk", "Ristretto shot", "Milk frother"]},
    {"id": "milk-flat-white", "name": "Flat White", "slug": "milk-flat-white",
     "note": "Cappuccino-sized, with less foam and more silky hot milk.",
     "items": ["4–5 oz milk", "Ristretto shot", "Milk frother"]},
    {"id": "milk-cortado", "name": "Cortado", "slug": "milk-cortado",
     "note": "A ristretto shot cut with 2–3 oz of warm milk and a little foam.",
     "items": ["2 oz milk", "Ristretto shot", "Milk frother"]},
    {"id": "milk-macchiato", "name": "Macchiato", "slug": "milk-macchiato",
     "note": "A ristretto shot marked with a spoonful of milk foam.",
     "items": ["2 oz milk", "Ristretto shot", "Milk frother"]},
    {"id": "milk-mocha", "name": "Mocha", "slug": "milk-mocha",
     "note": "Chocolate stirred into a ristretto shot, topped with frothed milk.",
     "items": ["4 oz milk", "Chocolate syrup", "Ristretto shot", "Milk frother"]},
    {"id": "milk-vanilla-latte", "name": "Vanilla Latte", "slug": "milk-vanilla-latte",
     "note": "Vanilla syrup and a ristretto shot under frothed milk.",
     "items": ["6 oz milk", "1 oz vanilla syrup", "Ristretto shot", "Milk frother"]},
]
MILK_IDS = {m["id"] for m in MILK_GUIDES}


def _rng(slider: dict | None, key: str) -> tuple[float, float] | None:
    r = (slider or {}).get(key)
    if isinstance(r, dict) and r.get("min") is not None and r.get("max") is not None and r["max"] > r["min"]:
        return float(r["min"]), float(r["max"])
    return None


def _clamp01(x: float) -> float:
    return max(0.0, min(1.0, x))


def _shots(recipe: dict) -> int:
    try:
        return max(1, int(recipe.get("shots") or 1))
    except (TypeError, ValueError):
        return 1


def is_visible(recipe: dict) -> bool:
    """Hide internal technical recipes (e.g. the brewer "Drying Recipe")."""
    if recipe.get("archived"):
        return False
    if recipe.get("type") == "technical" and (recipe.get("drink_size") or 0) <= 1:
        return False
    return bool(recipe.get("id") and recipe.get("name"))


def kind_of(recipe: dict) -> str:
    t = recipe.get("type")
    return {"custom": "custom", "technical": "special"}.get(t, "coffee")


def adjustable(recipe: dict) -> dict[str, Any]:
    """Human-unit ranges the recipe allows editing (empty = fixed recipe)."""
    s = recipe.get("slider") or {}
    out: dict[str, Any] = {}
    if (w := _rng(s, "coffee_weight")):
        out["strength"] = [w[0] / 10, w[1] / 10]  # grams
    if (v := _rng(s, "volume_extraction")):
        n = _shots(recipe)
        out["size"] = [round(v[0] * n), round(v[1] * n)]  # ml in the cup
    if (b := _rng(s, "water_balance")):
        out["balance"] = [b[0], b[1]]  # %
    if s.get("coffee_order"):
        out["order"] = True
    return out


def current_values(recipe: dict) -> dict[str, Any]:
    """The recipe's present settings in human units."""
    s = recipe.get("slider") or {}
    vals: dict[str, Any] = {}
    if recipe.get("coffee_weight"):
        vals["strength"] = round(recipe["coffee_weight"] / 10, 1)
    if recipe.get("drink_size"):
        vals["size"] = int(recipe["drink_size"])
    b = _rng(s, "water_balance")
    if b and recipe.get("water_balance_float") is not None:
        vals["balance"] = round(b[0] + recipe["water_balance_float"] * (b[1] - b[0]))
    if recipe.get("coffee_order") is not None:
        vals["coffee_first"] = not bool(recipe.get("coffee_order"))
    return vals


def summarize(recipe: dict) -> dict[str, Any]:
    """Slim catalog entry for Home Assistant / the Lovelace cards."""
    sp = recipe.get("special_params") or {}
    note = sp.get("release_notes") or ""
    if len(note) > 220:
        note = note[:217].rsplit(" ", 1)[0] + "…"
    return {
        "id": recipe.get("id"),
        "name": recipe.get("name"),
        "slug": recipe.get("slug"),
        "kind": kind_of(recipe),
        "parent": recipe.get("parent_name"),
        "shots": _shots(recipe),
        "cold": bool(recipe.get("cooldown_machine")),
        "values": current_values(recipe),
        "adjust": adjustable(recipe),
        "cup_ml": sp.get("cup_size_ml"),
        "items": [i.get("text") for i in (sp.get("required_items") or []) if isinstance(i, dict) and i.get("text")],
        "note": note or None,
    }


def milk_catalog(base: dict | None) -> list[dict[str, Any]]:
    """Milk guides as catalog entries (brewing them pours the ristretto base)."""
    vals = current_values(base) if base else {}
    return [
        {**m, "kind": "milk", "parent": base.get("name") if base else "Ristretto", "shots": 1,
         "cold": False, "values": vals, "adjust": {}, "cup_ml": None}
        for m in MILK_GUIDES
    ]


def build_catalog(library: list[dict]) -> list[dict[str, Any]]:
    """Visible server recipes (coffee, custom, specials) + the milk guides."""
    visible = [r for r in library if isinstance(r, dict) and is_visible(r)]
    base = next((r for r in visible if r.get("slug") == MILK_BASE_SLUG and r.get("type") == "spinn"), None)
    order = {"coffee": 0, "custom": 1, "special": 2}
    entries = sorted((summarize(r) for r in visible), key=lambda e: (order.get(e["kind"], 9), e["name"].lower()))
    return entries + milk_catalog(base)


def to_floats(
    recipe: dict,
    *,
    strength_g: float | None = None,
    size_ml: float | None = None,
    balance_pct: float | None = None,
    coffee_first: bool | None = None,
) -> dict[str, Any]:
    """Human units -> the API's slider fields, clamped to the recipe's ranges.

    Anything not given keeps the recipe's current value. Only fields the recipe
    supports are returned.
    """
    s = recipe.get("slider") or {}
    out: dict[str, Any] = {}

    if (w := _rng(s, "coffee_weight")):
        f = recipe.get("coffee_strength_float")
        if strength_g is not None:
            f = (float(strength_g) * 10 - w[0]) / (w[1] - w[0])
        if f is not None:
            out["coffee_strength_float"] = round(_clamp01(float(f)), 6)

    if (v := _rng(s, "volume_extraction")):
        f = recipe.get("water_level_float")
        if size_ml is not None:
            f = (float(size_ml) / _shots(recipe) - v[0]) / (v[1] - v[0])
        if f is not None:
            out["water_level_float"] = round(_clamp01(float(f)), 6)

    if (b := _rng(s, "water_balance")):
        f = recipe.get("water_balance_float")
        if balance_pct is not None:
            f = (float(balance_pct) - b[0]) / (b[1] - b[0])
        if f is not None:
            out["water_balance_float"] = round(_clamp01(float(f)), 6)

    if s.get("coffee_order"):
        if coffee_first is not None:
            out["coffee_order"] = 0 if coffee_first else 1
        elif recipe.get("coffee_order") is not None:
            out["coffee_order"] = int(recipe["coffee_order"])

    return out
