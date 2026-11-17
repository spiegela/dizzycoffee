"""Spinn backend REST client (auth + device/certificate fetch).

Request/response shapes are taken from the decompiled app (Retrofit + Gson
@SerializedName). See docs/PROTOCOL.md §2-3. This module only *reads* your
account and device record; it never actuates the machine.
"""
from __future__ import annotations

from typing import Any

import requests

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
