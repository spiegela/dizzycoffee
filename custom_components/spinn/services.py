"""Recipe services: brew any recipe once, save / install / delete custom recipes.

``brew_recipe`` actuates the machine (via the temporary slot + the same command
path as the Brew button). The others only change the Spinn account's cookbook
and custom recipes, which the cloud then syncs to the machine.
"""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN
from .coordinator import SpinnCoordinator

ATTR_DEVICE_ID = "device_id"
_VALUES = {
    vol.Optional("strength_g"): vol.All(vol.Coerce(float), vol.Range(min=0, max=30)),
    vol.Optional("size_ml"): vol.All(vol.Coerce(float), vol.Range(min=1, max=1000)),
    vol.Optional("balance_pct"): vol.All(vol.Coerce(float), vol.Range(min=0, max=100)),
    vol.Optional("coffee_first"): cv.boolean,
}
_DEVICE = {vol.Optional(ATTR_DEVICE_ID): cv.string}
_SLOT = vol.All(vol.Coerce(int), vol.Range(min=0, max=6))

BREW_SCHEMA = vol.Schema({vol.Required("recipe_id"): cv.string, **_VALUES, **_DEVICE})
SAVE_SCHEMA = vol.Schema({
    vol.Required("base_recipe_id"): cv.string,
    vol.Required("name"): vol.All(cv.string, vol.Length(min=1, max=40)),
    vol.Optional("slot"): _SLOT,
    **_VALUES, **_DEVICE,
})
INSTALL_SCHEMA = vol.Schema({vol.Required("recipe_id"): cv.string, vol.Required("slot"): _SLOT, **_DEVICE})
DELETE_SCHEMA = vol.Schema({vol.Required("recipe_id"): cv.string, **_DEVICE})


def _coordinator(hass: HomeAssistant, call: ServiceCall) -> SpinnCoordinator:
    coords: dict[str, SpinnCoordinator] = {
        k: v for k, v in hass.data.get(DOMAIN, {}).items() if isinstance(v, SpinnCoordinator)
    }
    device_id = call.data.get(ATTR_DEVICE_ID)
    if device_id:
        device = dr.async_get(hass).async_get(device_id)
        for entry_id in (device.config_entries if device else ()):
            if entry_id in coords:
                return coords[entry_id]
        raise ServiceValidationError(f"No Spinn machine for device {device_id}.")
    if len(coords) == 1:
        return next(iter(coords.values()))
    if not coords:
        raise ServiceValidationError("No Spinn machine is set up.")
    raise ServiceValidationError("Several Spinn machines are set up; pass device_id.")


def _values(call: ServiceCall) -> dict:
    return {k: call.data[k] for k in ("strength_g", "size_ml", "balance_pct", "coffee_first") if k in call.data}


def async_register_services(hass: HomeAssistant) -> None:
    """Register the recipe services once per Home Assistant instance."""
    if hass.services.has_service(DOMAIN, "brew_recipe"):
        return

    async def brew_recipe(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_brew_recipe(call.data["recipe_id"], **_values(call))

    async def save_recipe(call: ServiceCall) -> ServiceResponse:
        return await _coordinator(hass, call).async_save_recipe(
            call.data["base_recipe_id"], call.data["name"], call.data.get("slot"), **_values(call)
        )

    async def install_recipe(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_install_recipe(call.data["recipe_id"], call.data["slot"])

    async def delete_recipe(call: ServiceCall) -> None:
        await _coordinator(hass, call).async_delete_recipe(call.data["recipe_id"])

    hass.services.async_register(DOMAIN, "brew_recipe", brew_recipe, schema=BREW_SCHEMA)
    hass.services.async_register(
        DOMAIN, "save_recipe", save_recipe, schema=SAVE_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
    hass.services.async_register(DOMAIN, "install_recipe", install_recipe, schema=INSTALL_SCHEMA)
    hass.services.async_register(DOMAIN, "delete_recipe", delete_recipe, schema=DELETE_SCHEMA)
