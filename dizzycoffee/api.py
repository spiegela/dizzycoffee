"""Spinn backend REST client (auth + device/certificate fetch).

Request/response shapes are taken from the decompiled app (Retrofit + Gson
@SerializedName). See docs/PROTOCOL.md §2-3. This module only *reads* your
account and device record; it never actuates the machine.
"""
from __future__ import annotations

from typing import Any

import requests

from .recipes import BREWABLE_SLOTS, SLOT_ROLES

USER_AGENT = "DizzyCoffee/0.1 (+https://github.com/spiegela/dizzycoffee)"
TIMEOUT = 20


class SpinnError(RuntimeError):
    def __init__(self, message: str, status: int | None = None, body: str | None = None):
        super().__init__(message)
        self.status = status
        self.body = body


class SpinnClient:
    """Thin client over www.spinn.com/api/ (auth) and iot.spinn.com/ (devices)."""

    def __init__(self, mp_base: str, iot_base: str, access_token: str | None = None):
        self.mp_base = mp_base.rstrip("/") + "/"
        self.iot_base = iot_base.rstrip("/") + "/"
        self.access_token = access_token
        self._s = requests.Session()
        self._s.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})

    # --- low level ----------------------------------------------------------
    def _url(self, base: str, path: str) -> str:
        return base + path.lstrip("/")

    def _request(self, method: str, url: str, *, auth: bool = False, **kw) -> Any:
        headers = dict(kw.pop("headers", {}))
        if auth:
            if not self.access_token:
                raise SpinnError("not authenticated: run `login` first")
            # [L] Bearer scheme per AuthenticationRequestInterceptor; confirm on first authed call.
            headers["Authorization"] = f"Bearer {self.access_token}"
        resp = self._s.request(method, url, headers=headers, timeout=TIMEOUT, **kw)
        if not resp.ok:
            raise SpinnError(
                f"{method} {url} -> HTTP {resp.status_code}",
                status=resp.status_code,
                body=resp.text[:500],
            )
        if resp.content and "application/json" in resp.headers.get("content-type", ""):
            return resp.json()
        return resp.text

    # --- auth ---------------------------------------------------------------
    @staticmethod
    def _token_from(auth_response: Any) -> dict:
        """InlineResponseAuth = {account, token}; return the token dict."""
        if isinstance(auth_response, dict) and "token" in auth_response:
            return auth_response["token"]
        return auth_response  # tolerate a bare token payload

    def login_password(self, email: str, password: str) -> dict:
        """POST auth/login {email, password} -> token dict."""
        body = self._request(
            "POST", self._url(self.mp_base, "auth/login"),
            json={"email": email, "password": password},
        )
        token = self._token_from(body)
        self.access_token = token.get("access_token")
        return token

    def login_amazon(self, lwa_access_token: str, auth_type: str = "amazon") -> dict:
        """POST auth/amazon {token, auth_type} -> token dict (Login-with-Amazon path)."""
        body = self._request(
            "POST", self._url(self.mp_base, "auth/amazon"),
            json={"token": lwa_access_token, "auth_type": auth_type},
        )
        token = self._token_from(body)
        self.access_token = token.get("access_token")
        return token

    def refresh(self, token: dict) -> dict:
        """POST auth/token (body = stored Token) -> fresh token dict."""
        body = self._request(
            "POST", self._url(self.mp_base, "auth/token"), json=token,
        )
        new = self._token_from(body)
        self.access_token = new.get("access_token")
        return new

    # --- devices ------------------------------------------------------------
    def get_devices(self) -> list[dict]:
        """GET link/api/devices -> list of Device records.

        Note: the list carries only a certificate *stub* (arn/id, no PEM/key).
        Use get_device() for the full record with certificate_pem/private_key.
        """
        body = self._request(
            "GET", self._url(self.iot_base, "link/api/devices"), auth=True,
        )
        if isinstance(body, list):
            return body
        # Some deployments wrap lists; be forgiving.
        if isinstance(body, dict):
            for key in ("devices", "data", "items", "results"):
                if isinstance(body.get(key), list):
                    return body[key]
        raise SpinnError("unexpected devices payload", body=str(body)[:300])

    def get_device(self, thing_name: str) -> dict:
        """GET link/api/devices/{thing_name} -> full Device record.

        This is the only endpoint that returns the usable client certificate
        (certificate.certificate_pem + certificate.certificate_private_key).
        """
        body = self._request(
            "GET", self._url(self.iot_base, f"link/api/devices/{thing_name}"), auth=True,
        )
        if isinstance(body, dict):
            return body
        if isinstance(body, list) and body:
            return body[0]
        raise SpinnError("unexpected device payload", body=str(body)[:300])

    # --- recipes (read-only) ------------------------------------------------
    def get_cookbook(self, thing_name: str) -> dict:
        """GET recipe/api/cookbook?thing_name=... -> the machine's installed slots.

        ``{"thing_name", "slots": [{"recipe_id", "status", ...}, ...]}``.
        ``slots[i]`` is brewed with slot byte ``i`` (0-based; = shadow
        ``RecipeNumber``). Layout per the app (``Cookbook``/``RecipesRepository``):
        0-3 user slots, 4/5/6 the machine's tall/medium/small cup buttons, 7 the
        temporary slot for one-off brews. Without ``thing_name`` the endpoint 404s.
        """
        body = self._request(
            "GET", self._url(self.iot_base, "recipe/api/cookbook"),
            params={"thing_name": thing_name}, auth=True,
        )
        if isinstance(body, dict) and isinstance(body.get("slots"), list):
            return body
        raise SpinnError("unexpected cookbook payload", body=str(body)[:300])

    def get_recipes(self, thing_name: str, all: bool = False) -> list[dict]:  # noqa: A002
        """GET recipe/api/recipes?thing_name=...[&all=true] -> recipe records.

        Default: the account's library (stock + the user's custom recipes).
        ``all=True`` adds the "technical" specials (Affogato, Espresso Martini…)
        the app lists under Specials. Milk drinks are not here: the app
        hard-codes them as a ristretto shot plus frothing instructions.
        """
        params = {"thing_name": thing_name}
        if all:
            params["all"] = "true"
        body = self._request(
            "GET", self._url(self.iot_base, "recipe/api/recipes"), params=params, auth=True,
        )
        if isinstance(body, list):
            return body
        raise SpinnError("unexpected recipes payload", body=str(body)[:300])

    def get_installed_recipes(self, thing_name: str, library: list[dict] | None = None) -> list[dict]:
        """Cookbook slots joined to their recipe records, one dict per slot.

        Each item: ``{slot, role, recipe_id, name, slug, type, drink_size,
        shots, cold, image_url}``. ``slot`` is the 0-based brew byte; ``role``
        is ``user1``..``user4``, ``tall``/``medium``/``small`` (the machine's
        cup buttons) or ``temp``. ``type`` is ``"spinn"``, ``"custom"`` or
        ``"technical"``; ``drink_size`` is ml. Unresolvable slots keep
        ``name=None``.
        """
        book = self.get_cookbook(thing_name)
        if library is None:
            library = self.get_recipes(thing_name, all=True)
        by_id = {r.get("id"): r for r in library if isinstance(r, dict)}
        out: list[dict] = []
        for i, slot in enumerate(book.get("slots") or []):
            rid = (slot or {}).get("recipe_id")
            r = by_id.get(rid, {})
            out.append({
                "slot": i,
                "role": SLOT_ROLES.get(i),
                "recipe_id": rid,
                "name": r.get("name"),
                "slug": r.get("slug"),
                "type": r.get("type"),
                "drink_size": r.get("drink_size"),
                "shots": r.get("shots"),
                "cold": bool(r.get("cooldown_machine")),
                "image_url": r.get("image_url"),
            })
        return out

    # --- recipe writes ------------------------------------------------------
    # These change the Spinn ACCOUNT (the cloud then syncs the cookbook to the
    # machine). None of them brews. Bodies are the app's own (docs §3, [V] for
    # temporary-slot and create/delete, exercised live 2026-11-17).
    @staticmethod
    def _clean(body: dict) -> dict:
        return {k: v for k, v in body.items() if v is not None}

    def set_temporary_slot(self, thing_name: str, recipe_id: str, **floats: Any) -> dict:
        """PUT recipe/api/cookbook/temporary-slot — stage a one-off recipe in slot 7.

        ``floats`` may carry ``coffee_strength_float``, ``water_level_float``,
        ``water_balance_float``, ``coffee_order`` (see ``recipes.to_floats``).
        Brew it afterwards with PREPARE_RECIPE + 7.
        """
        return self._request(
            "PUT", self._url(self.iot_base, "recipe/api/cookbook/temporary-slot"), auth=True,
            json=self._clean({"thing_name": thing_name, "recipe_id": recipe_id, **floats}),
        )

    def create_custom_recipe(
        self, thing_name: str, recipe_slug: str, name: str, **floats: Any
    ) -> dict:
        """POST recipe/api/recipes — save a custom copy of the base recipe ``recipe_slug``."""
        body = self._request(
            "POST", self._url(self.iot_base, "recipe/api/recipes"), auth=True,
            json=self._clean({"thing_name": thing_name, "recipe_slug": recipe_slug, "name": name, **floats}),
        )
        if isinstance(body, dict) and body.get("id"):
            return body
        raise SpinnError("unexpected create-recipe payload", body=str(body)[:300])

    def set_cookbook_slot(self, thing_name: str, slot: int, recipe_id: str) -> dict:
        """PUT recipe/api/cookbook/slot — install ``recipe_id`` into ``slot`` (0-6)."""
        if slot not in BREWABLE_SLOTS:
            raise SpinnError(f"slot must be 0-6, got {slot}")
        return self._request(
            "PUT", self._url(self.iot_base, "recipe/api/cookbook/slot"), auth=True,
            json={"thing_name": thing_name, "slot": int(slot), "recipe_id": recipe_id},
        )

    def delete_custom_recipe(self, recipe_id: str) -> Any:
        """DELETE recipe/api/recipes/{id} — remove one of the user's custom recipes."""
        return self._request(
            "DELETE", self._url(self.iot_base, f"recipe/api/recipes/{recipe_id}"), auth=True,
        )
