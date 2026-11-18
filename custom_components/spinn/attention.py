"""What on the machine needs a person: refills, emptying, maintenance, errors.

Pure functions over the shadow ``reported`` dict, shared by the Needs attention
binary sensor, the brew-failure hint and diagnostics. The level rules mirror the
machine card (``frontend/spinn-card.js``) so the dashboard and automations agree:

* Beans / water: empty (``EMPTY``, ``EMPTYORREMOVED``, ``REMOVED``) needs a refill;
  ``LEVEL0`` is low.
* Grounds bin / drip tray: ``FULL`` or removed needs emptying / putting back;
  ``LEVEL2`` is nearly full.
* Deep clean / descale: due once the cups-since counter reaches its interval.

``reasons`` are things to do now (they turn the binary sensor on); ``warnings``
are heads-ups (low / nearly full) that don't.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .const import DEFAULT_DEEP_CLEAN_EVERY, DEFAULT_DESCALE_EVERY

_EMPTY = {"EMPTY", "EMPTYORREMOVED", "REMOVED"}
_LOW = {"LEVEL0"}
_REMOVED = {"REMOVED", "EMPTYORREMOVED"}
_NEARLY_FULL = {"LEVEL2"}

# Reason / warning key -> phrase used in error messages ("Check the machine: ...").
PHRASES: dict[str, str] = {
    "machine_error": "it reports an error",
    "water_tank_empty": "the water tank is empty",
    "beans_empty": "the bean hopper is empty",
    "grounds_bin_full": "the grounds bin is full",
    "grounds_bin_removed": "the grounds bin is out",
    "drip_tray_full": "the drip tray is full",
    "drip_tray_removed": "the drip tray is out",
    "deep_clean_due": "a deep clean is due",
    "descale_due": "descaling is due",
    "water_tank_low": "the water tank is low",
    "beans_low": "the beans are low",
    "grounds_bin_nearly_full": "the grounds bin is nearly full",
    "drip_tray_nearly_full": "the drip tray is nearly full",
}


@dataclass(frozen=True)
class Attention:
    """Reasons (act now) and warnings (heads-up), as stable keys."""

    reasons: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def needed(self) -> bool:
        return bool(self.reasons)


def _level(data: dict[str, Any], key: str) -> str | None:
    val = data.get(key)
    if val in (None, ""):
        return None
    return str(val).upper()


def _count(data: dict[str, Any], key: str) -> int | None:
    val = data.get(key)
    if val in (None, ""):
        return None
    try:
        return int(float(val))
    except (TypeError, ValueError):
        return None


def evaluate(
    data: dict[str, Any] | None,
    *,
    deep_clean_every: int = DEFAULT_DEEP_CLEAN_EVERY,
    descale_every: int = DEFAULT_DESCALE_EVERY,
) -> Attention:
    """Work out what needs attention from a shadow ``reported`` dict."""
    data = data or {}
    reasons: list[str] = []
    warnings: list[str] = []

    if data.get("MachineStatus") == "MACHINEERROR":
        reasons.append("machine_error")

    for key, name in (("WaterTank", "water_tank"), ("HopperReservoir", "beans")):
        level = _level(data, key)
        if level in _EMPTY:
            reasons.append(f"{name}_empty")
        elif level in _LOW:
            warnings.append(f"{name}_low")

    for key, name in (("ResidueBin", "grounds_bin"), ("DripTray", "drip_tray")):
        level = _level(data, key)
        if level in _REMOVED:
            reasons.append(f"{name}_removed")
        elif level == "FULL":
            reasons.append(f"{name}_full")
        elif level in _NEARLY_FULL:
            warnings.append(f"{name}_nearly_full")

    for key, name, every in (
        ("NoDeepCleanCounter", "deep_clean_due", deep_clean_every),
        ("NoDescaleCounter", "descale_due", descale_every),
    ):
        count = _count(data, key)
        if every > 0 and count is not None and count >= every:
            reasons.append(name)

    return Attention(reasons=reasons, warnings=warnings)


def describe(keys: list[str]) -> str:
    """Join reason/warning keys into a readable phrase list."""
    phrases = [PHRASES.get(k, k.replace("_", " ")) for k in keys]
    if not phrases:
        return ""
    if len(phrases) == 1:
        return phrases[0]
    return ", ".join(phrases[:-1]) + " and " + phrases[-1]
