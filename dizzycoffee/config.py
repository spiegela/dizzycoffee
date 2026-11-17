"""Configuration and local session storage.

Secrets never live in the repo. The session token is stored under the user's
config dir (default ~/.config/dizzycoffee/session.json), chmod 600. Endpoints
default to the values baked into the official app and can be overridden via
env vars or an optional config.toml (also outside the repo).
"""
from __future__ import annotations

import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path

# Baked-in defaults recovered from the official app (com.spinn.spinncoffee.app.AppConfig).
DEFAULT_MP_BASE = "https://www.spinn.com/api/"
DEFAULT_IOT_BASE = "https://iot.spinn.com/"
DEFAULT_IOT_ENDPOINT = "a1gzieuy3t1932.iot.us-east-1.amazonaws.com"


def _config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "dizzycoffee"


@dataclass
class Config:
    mp_base: str = DEFAULT_MP_BASE
    iot_base: str = DEFAULT_IOT_BASE
    iot_endpoint: str = DEFAULT_IOT_ENDPOINT
    email: str | None = None  # convenience default for `login`; password is never stored
    session_path: Path = None  # type: ignore[assignment]

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        # Optional TOML (outside the repo); tolerate its absence.
        toml_path = _config_dir() / "config.toml"
        if toml_path.exists():
            try:
                import tomllib  # py311+
                data = tomllib.loads(toml_path.read_text())
            except Exception:
                data = {}
            cfg.mp_base = data.get("mp_base", cfg.mp_base)
            cfg.iot_base = data.get("iot_base", cfg.iot_base)
            cfg.iot_endpoint = data.get("iot_endpoint", cfg.iot_endpoint)
            cfg.email = data.get("email", cfg.email)
        # Env overrides win.
        cfg.mp_base = os.environ.get("DIZZY_MP_BASE", cfg.mp_base)
        cfg.iot_base = os.environ.get("DIZZY_IOT_BASE", cfg.iot_base)
        cfg.iot_endpoint = os.environ.get("DIZZY_IOT_ENDPOINT", cfg.iot_endpoint)
        cfg.email = os.environ.get("DIZZY_EMAIL", cfg.email)
        cfg.session_path = Path(
            os.environ.get("DIZZY_SESSION", _config_dir() / "session.json")
        )
        return cfg

    # --- session token persistence ------------------------------------------
    def read_session(self) -> dict | None:
        try:
            return json.loads(self.session_path.read_text())
        except FileNotFoundError:
            return None
        except Exception:
            return None

    def write_session(self, token: dict) -> None:
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(token, indent=2))
        try:
            self.session_path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 600
        except OSError:
            pass

    def clear_session(self) -> None:
        try:
            self.session_path.unlink()
        except FileNotFoundError:
            pass
