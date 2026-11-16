"""Per-file setting blocks (```resolution, ```aspect_ratio, ```audio), checked against the model.

A block is accepted only when the profile's model has that setting in its own
endpoint file in the engine, and, for a list setting, only with one of its
options. A block named after a setting some other model of the engine has but
this one lacks (e.g. ```size on Seedance 2.5) is refused too. Any other fenced
block is not a setting block.
"""

import importlib.util
from pathlib import Path
from typing import Any

import tomllib

# block name → the model's parameter names that can carry it, first found wins
BLOCK_PARAMS = {
    "resolution": ("resolution",),
    "aspect_ratio": ("aspect_ratio", "ratio"),
    "audio": ("generate_audio",),
}
_AUDIO_VALUES = {"on": True, "true": True, "yes": True, "off": False, "false": False, "no": False}
_NOT_SETTINGS = {"duration", "prompt"}


def _endpoint_files(platform: str, search_paths: list[Path]) -> list[Path]:
    pkg = f"engine_{platform}"
    roots = [sp / f"engine-{platform}" / pkg for sp in search_paths]
    try:
        spec = importlib.util.find_spec(pkg)
    except (ImportError, ValueError):
        spec = None
    if spec is not None and spec.origin:
        roots.append(Path(spec.origin).parent)
    for root in roots:
        files = sorted((root / "endpoints").glob("*/*.toml"))
        if files:
            return files
    return []


def model_settings(
    platform: str, endpoint: str | None, search_paths: list[Path]
) -> tuple[dict[str, Any], set[str]]:
    """Return (this model's params, every param name any model of the engine has)."""
    model: dict[str, Any] = {}
    known: set[str] = set()
    for path in _endpoint_files(platform, search_paths):
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        params = data.get("params") or {}
        known.update(params)
        if endpoint and data.get("endpoint") == endpoint:
            model = params
    return model, known


def block_names(model: dict[str, Any], known: set[str]) -> set[str]:
    """Fence names the parser reads as setting blocks."""
    return set(BLOCK_PARAMS) | (known - set(model) - _NOT_SETTINGS)


def check_settings(blocks: dict[str, str], model: dict[str, Any]) -> dict[str, Any]:
    """Map accepted blocks to parameter overrides; ValueError names a refused block and value."""
    overrides: dict[str, Any] = {}
    for name, value in blocks.items():
        key = next((k for k in BLOCK_PARAMS.get(name, ()) if k in model), None)
        if key is None:
            raise ValueError(f"```{name} {value}: this model has no {name} setting")
        if name == "audio":
            if value.lower() not in _AUDIO_VALUES:
                raise ValueError(f"```audio {value}: use on/off, true/false or yes/no")
            overrides[key] = _AUDIO_VALUES[value.lower()]
            continue
        options = [
            str(o.get("value", o)) if isinstance(o, dict) else str(o)
            for o in model[key].get("options") or []
        ]
        if options and value not in options:
            raise ValueError(f"```{name} {value}: this model takes {', '.join(options)}")
        overrides[key] = value
    return overrides
