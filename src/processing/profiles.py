"""Profile loading — standalone and studiolot modes."""

import shutil
from pathlib import Path
from typing import Any

import yaml

from ..exceptions import ConfigurationError

_ACTIVE = Path("USER-FILES/03.PROFILES")
_STANDBY = Path("USER-FILES/02.STANDBY")


def _parse_profile_yaml(yaml_path: Path) -> dict[str, Any]:
    """Load and annotate a profile YAML file."""
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    data["profile_name"] = yaml_path.stem
    data["profile_path"] = str(yaml_path)
    return data


def normalize_legacy_profile(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize old profile formats (Model, duration_config) to Engine-interface keys."""
    if "Model" in data and "endpoint" not in data:
        data["endpoint"] = data["Model"].get("endpoint", "")

    if "platform" not in data:
        data["platform"] = "replicate"

    if "media_type" not in data:
        data["media_type"] = "video"

    if "image_url_param" not in data and "image_url" in data:
        data["image_url_param"] = data["image_url"]

    if "duration_config" in data or "params" in data or "parameters" not in data:
        params: dict[str, Any] = dict(data.get("parameters") or {})
        if not params and isinstance(data.get("params"), dict):
            params = dict(data["params"])
        dc = data.get("duration_config", {}) or {}
        if "fps" not in params:
            params["fps"] = data.get("fps", dc.get("fps", 24))
        if "duration" not in params and "duration_min" in data:
            params["duration"] = data["duration_min"]
        data["parameters"] = params

    params = data.get("parameters", {})
    if "fps" not in params:
        params["fps"] = 24

    return data


def list_standby() -> list[Path]:
    """Return sorted YAML paths available on the STANDBY shelf."""
    return sorted(_STANDBY.glob("*.yaml")) + sorted(_STANDBY.glob("*.yml"))


def activate_profile(source: Path) -> Path:
    """Copy a YAML from STANDBY into 03.PROFILES/ to make it active.

    Returns the destination path.
    """
    _ACTIVE.mkdir(parents=True, exist_ok=True)
    dest = _ACTIVE / source.name
    shutil.copy2(str(source), str(dest))
    return dest


def load_profile_standalone() -> dict[str, Any]:
    """Load the active profile from 03.PROFILES/ — never falls back to STANDBY."""
    yamls = sorted(_ACTIVE.glob("*.yaml")) + sorted(_ACTIVE.glob("*.yml"))
    if not yamls:
        raise ConfigurationError(
            "No active profile in USER-FILES/03.PROFILES/.\n"
            "Copy a YAML from USER-FILES/02.STANDBY/ into USER-FILES/03.PROFILES/"
        )
    data = normalize_legacy_profile(_parse_profile_yaml(yamls[0]))
    return data


def load_profile_studiolot(profile_path: Path) -> dict[str, Any]:
    """Load profile YAML from --profile flag."""
    if not profile_path.exists():
        raise ConfigurationError(f"Profile not found: {profile_path}")
    return _parse_profile_yaml(profile_path)
