"""Engine discovery, installation, input construction, and loading."""

import importlib
import inspect
import subprocess
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from .constants import MEDIA_TYPE
from .datatypes import Markdown
from .engine_contract import validate_input_file
from .engine_loader import EngineLoadContext, copy_standby_profiles, load_engine
from .exceptions import ConfigurationError


def find_project_engines_dir(start_dir: Path, max_depth: int = 10) -> Path | None:
    """Walk up from start_dir looking for 00_APPLICATIONS/ENGINES/."""
    current = start_dir.resolve()
    for _ in range(max_depth):
        candidate = current / "00_APPLICATIONS" / "ENGINES"
        if candidate.is_dir():
            return candidate
        if current.parent == current:
            break
        current = current.parent
    return None


def find_generator_engines_dir() -> Path:
    """Return <generator-root>/ENGINES/."""
    return Path(__file__).resolve().parent.parent / "ENGINES"


def print_engine_not_found(platform: str) -> None:
    from .auth import SUPPORTED_PLATFORMS, _key_name

    lines = [f"\nError: No Engine found for platform '{platform}'.\n\n"]

    lines.append("Supported platforms:\n\n")
    for p in SUPPORTED_PLATFORMS:
        p_key = _key_name(p)
        marker = "  ← default" if p == platform else ""
        lines.append(f"  [{p}]{marker}\n")
        lines.append(
            f"    git clone https://github.com/vivid-allusion/engine-{p}.git "
            f"ENGINES/engine-{p}/\n"
        )
        lines.append(f"    pip install engine-{p}\n")
        lines.append(f"    {p_key}=...  (in .env)\n")
        lines.append("\n")

    lines.append(
        "To auto-install the default engine:  python3 run.py --install-default-engine=replicate\n"
    )

    sys.stderr.write("".join(lines))


def auto_install_engine(platform: str, generator_root: Path | None = None) -> bool:
    if generator_root is None:
        generator_root = Path(__file__).resolve().parent.parent
    engines_dir = generator_root / "ENGINES"
    engines_dir.mkdir(exist_ok=True)
    target = engines_dir / f"engine-{platform}"

    if target.is_dir():
        logger.info(f"Engine directory already exists: {target}")
        return True

    repo_url = f"https://github.com/vivid-allusion/engine-{platform}.git"
    logger.info(f"Cloning {repo_url} -> {target}")
    result = subprocess.run(
        ["git", "clone", repo_url, str(target)],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        logger.error(f"git clone failed: {result.stderr}")
        return False

    req = target / "requirements.txt"
    if req.exists():
        logger.info("Installing Engine dependencies...")
        pip_result = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        if pip_result.returncode != 0:
            logger.error(f"pip install failed: {pip_result.stderr}")
            return False

    logger.success(f"Engine '{platform}' installed")
    return True


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clamp_duration(
    duration: int | float | str,
    duration_min: Any = None,
    duration_max: Any = None,
) -> int | float | str:
    """Clamp a non-negative numeric duration into the profile's bounds.

    Negative sentinels (-1) and non-numeric tokens (`auto`) pass through
    verbatim; a missing or non-numeric bound leaves that side unclamped.
    """
    if not _is_number(duration) or duration < 0:
        return duration
    if _is_number(duration_min) and duration < duration_min:
        duration = duration_min
    if _is_number(duration_max) and duration > duration_max:
        duration = duration_max
    return duration


def build_inputs(
    markdown_files: list[Markdown],
    platform: str,
    input_root: Path | None = None,
    profile: dict[str, Any] | None = None,
) -> list[Any]:
    """Construct InputFile objects using the Engine's datatype.

    metadata carries {duration, fps} per GENERATOR_CONTRACT.md §4d, plus
    relative_dir so outputs mirror the input folder structure. The Markdown file's
    raw `duration:` wins over `frames:`/profile default; an effective numeric
    duration then clamps into the profile's top-level `duration_min`/`duration_max`
    (verbatim within profile bounds — negative sentinels and tokens pass through).
    """
    try:
        pkg = importlib.import_module(f"engine_{platform}")
        InputFile = pkg.InputFile
    except (ImportError, AttributeError) as e:
        raise ImportError(
            f"Engine '{platform}' is missing or does not export InputFile: {e}"
        ) from e
    validate_input_file(InputFile, platform)

    params = (profile or {}).get("parameters", {})
    fps = int(params.get("fps", 24))
    profile_duration = params.get("duration", 5)
    duration_min = (profile or {}).get("duration_min")
    duration_max = (profile or {}).get("duration_max")

    preset_refs = list((profile or {}).get("reference_images") or [])
    declared_slots = list((profile or {}).get("slots") or [])
    routes_to_declared_slot = "reference_images" in declared_slots

    accepts_references = "references" in inspect.signature(InputFile.__init__).parameters

    if routes_to_declared_slot and preset_refs and not accepts_references:
        raise ConfigurationError(
            f"Engine '{platform}' declares the 'reference_images' slot but its "
            "InputFile does not accept references — cannot route the profile's "
            "reference_images without dropping them"
        )

    if not accepts_references and (
        any(b.get("references") for b in markdown_files) or preset_refs
    ):
        logger.warning(
            f"Engine '{platform}' does not support named reference slots — "
            "slot URLs in the Markdown files are ignored and the profile's "
            "reference_images fall back to reference_urls"
        )

    inputs = []
    for b in markdown_files:
        raw_duration = b.get("duration")
        if raw_duration is not None:
            duration = raw_duration
        elif b["frames"]:
            duration = b["frames"] / fps
        else:
            duration = profile_duration
        duration = clamp_duration(duration, duration_min, duration_max)
        references = dict(b.get("references") or {})
        reference_urls = list(b["reference_urls"])
        if preset_refs:
            if routes_to_declared_slot:
                references["reference_images"] = [
                    *references.get("reference_images", []),
                    *preset_refs,
                ]
            else:
                reference_urls = [*reference_urls, *preset_refs]
        kwargs: dict[str, Any] = {
            "path": b["path"],
            "prompt": b["prompt"],
            "reference_urls": reference_urls,
            "metadata": {
                "duration": duration,
                "fps": fps,
                "relative_dir": _relative_dir(b["path"].parent, input_root),
            },
        }
        if accepts_references:
            kwargs["references"] = references
        inputs.append(InputFile(**kwargs))
    return inputs


def _relative_dir(dir_path: Path, input_root: Path | None) -> str:
    """Return dir_path relative to input_root as a posix string ('' if root)."""
    if input_root is None:
        return ""
    try:
        rel = dir_path.relative_to(input_root)
    except ValueError:
        return ""
    return "" if rel == Path(".") else rel.as_posix()


def _emit_progress(msg: Any) -> None:
    """Write progress message to stderr immediately.

    msg may be a str or a ProgressEvent (duck-typed — any object with .message).
    """
    text = msg.message if hasattr(msg, "message") else str(msg)
    sys.stderr.write(f"{text}\n")
    sys.stderr.flush()


def make_engine_ctx(
    platform: str,
    search_paths: list[Path],
    profile: dict[str, Any],
    output_dir: Path,
    api_key: str | None,
) -> EngineLoadContext:
    return EngineLoadContext(
        platform=platform,
        search_paths=search_paths,
        profile=profile,
        output_dir=output_dir,
        api_key=api_key,
        on_progress=lambda msg: _emit_progress(msg),
    )


def load_engine_or_install(
    platform: str,
    search_paths: list[Path],
    profile: dict[str, Any],
    output_dir: Path,
    api_key: str | None,
    auto_install: str | None = None,
) -> Any:
    """Load engine with optional auto-install fallback on FileNotFoundError."""
    ctx = make_engine_ctx(platform, search_paths, profile, output_dir, api_key)
    try:
        engine = load_engine(ctx)
    except FileNotFoundError:
        if not auto_install:
            raise
        logger.info(f"Auto-installing Engine: {auto_install}")
        if not auto_install_engine(auto_install):
            raise FileNotFoundError(f"Failed to auto-install engine '{auto_install}'")
        engine = load_engine(ctx)
    copied = copy_standby_profiles(platform, media_type=MEDIA_TYPE)
    if copied:
        logger.debug(f"Seeded {copied} standby profile(s) from engine-{platform}")
    return engine
