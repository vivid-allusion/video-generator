"""Generation payload embedding — marry each generated video to its recipe.

``compose_payload()`` builds the recipe JSON (schema v1, byte-compatible with
image-generator), ``payload_text()`` serialises it, and ``stamp_saved_file()``
writes it into the MP4's Adobe-XMP ``uuid`` box without ever failing a run.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from ..constants import __version__
from .payload_containers import append_xmp, xmp_packet


def _relative_posix(path: Path, root: Path | None) -> str | None:
    """Return path relative to root as a posix string, or None when outside."""
    if root is None:
        return None
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return None


def _video_duration(
    item: Any, profile: dict[str, Any], api_payload: dict | None
) -> Any:
    """Resolve the effective requested duration: provider payload first.

    Keeps numeric values and tokens (``auto``, ``-1``) verbatim. Never guesses
    from the saved file.
    """
    key = str(profile.get("duration_param_name") or "duration")
    if isinstance(api_payload, dict) and key in api_payload:
        return api_payload[key]
    metadata = getattr(item, "metadata", None) or {}
    return metadata.get("duration")


def compose_payload(
    *,
    item: Any,
    final_path: Path,
    profile: dict[str, Any],
    platform: str,
    engine: Any,
    input_root: Path | None,
    api_payload: dict | None = None,
) -> dict[str, Any]:
    """Build the recipe JSON (schema 1) for one generated video."""
    prefix = str(profile.get("prompt_prefix", "") or "")
    suffix = str(profile.get("prompt_suffix", "") or "")
    raw = item.prompt
    parameters = dict(profile.get("parameters", {}))
    parameters.pop("save_payloads", None)
    preset_refs = list(profile.get("reference_images") or [])

    payload: dict[str, Any] = {
        "schema": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": {"name": "video-generator", "version": __version__},
        "engine": {
            "platform": platform,
            "provider": getattr(engine, "PROVIDER_NAME", platform),
        },
        "endpoint": profile.get("endpoint", ""),
        "parameters": parameters,
        "prompt": {"raw": raw, "wrapped": f"{prefix}{raw}{suffix}".strip()},
        "prefix": prefix,
        "suffix": suffix,
        "reference_urls": list(getattr(item, "reference_urls", None) or []),
        "input_file": _relative_posix(item.path, input_root) or item.path.name,
        "media_type": "video",
        "video_duration": _video_duration(item, profile, api_payload),
        "output_file": final_path.name,
    }
    if preset_refs:
        payload["preset_reference_urls"] = preset_refs
    return payload


def payload_text(
    *,
    item: Any,
    final_path: Path,
    profile: dict[str, Any],
    platform: str,
    engine: Any,
    input_root: Path | None,
    api_payload: dict | None = None,
) -> str:
    """Serialise one video's recipe payload exactly as it is embedded."""
    return json.dumps(
        compose_payload(
            item=item,
            final_path=final_path,
            profile=profile,
            platform=platform,
            engine=engine,
            input_root=input_root,
            api_payload=api_payload,
        ),
        indent=2,
        ensure_ascii=False,
    )


def stamp_path(path: Path, text: str) -> None:
    """Embed an XMP packet carrying ``text`` into the MP4 at ``path``."""
    append_xmp(path, xmp_packet(text))


def stamp_saved_file(path: Path, text: str) -> bool:
    """Stamp the staged .part file; never raise into the engine.

    Returns True when the packet was written, False when stamping was skipped
    (non-MP4, unreadable, or moved file). A failed stamp must never mask a
    successful generation — the end-of-run pass may retry it.
    """
    try:
        stamp_path(path, text)
    except Exception as exc:  # best effort: generation already succeeded
        logger.debug(f"Payload stamp deferred for {path.name}: {exc}")
        return False
    logger.debug(f"Payload embedded: {path.name}")
    return True
