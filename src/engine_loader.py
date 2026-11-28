"""Canonical Engine discovery and loading — vendored from the Transceiver.

Per ENGINE_CONTRACT.md §6/§7a: the canonical implementation of load_engine()
lives in ~/MISC/helmer-transceiver/hhc/engines.py. This file is the Generator's
byte-identical snapshot of that module's *loader half* — change the canonical
first, then re-vendor (verify with a three-way diff).

accepted divergence (W5 M5): hc/engines.py is a facet — it also imports
hc.engine_registry and hc.surface and exports `engines_list` / `OPS`, which
do not exist in a Generator. Only the loader functions below are vendored; this
Generator's copy stays byte-identical to the other Generator's.
"""

import importlib
import importlib.util
import shutil
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .constants import DEFAULT_PLATFORM


def _ensure_engine_dependencies(engine_dir: Path) -> None:
    """Install engine dependencies if requirements.txt is present.

    Idempotent: pip install -r is a no-op when everything is already
    satisfied. Called before importing the engine package so that a
    generator-created venv (which only has generator deps) gets the engine
    SDK automatically.
    """
    req = engine_dir / "requirements.txt"
    if not req.exists():
        return
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
            check=True,
            capture_output=True,
        )
    except subprocess.CalledProcessError as e:
        stderr = e.stderr.decode() if e.stderr else ""
        raise ImportError(
            f"Engine dependencies at {req} failed to install. pip stderr: {stderr}"
        ) from e


@dataclass
class EngineLoadContext:
    """Bundled parameters for `load_engine()`.

    Collapses the old 6-param signature into a single typed object.
    """

    platform: str | None
    search_paths: list[Path]
    profile: dict[str, Any]
    output_dir: str | Path
    api_key: str | None = None
    on_progress: Callable[[str], None] | None = None


def find_engine_dir(search_paths: list[Path], platform: str | None) -> Path:
    """Return the first engine-<platform> directory found in search_paths.

    Raises:
        FileNotFoundError: No Engine directory found in search_paths.
    """
    resolved = platform or DEFAULT_PLATFORM
    engine_dir_name = f"engine-{resolved}"
    for sp in search_paths:
        candidate = sp / engine_dir_name
        if candidate.is_dir():
            return candidate
    searched = "\n  ".join(str(sp / engine_dir_name) for sp in search_paths)
    raise FileNotFoundError(f"Engine '{resolved}' not found. Searched:\n  {searched}")


def find_first_engine_dir(search_paths: list[Path]) -> tuple[Path, str] | None:
    """Return (dir, platform) of the first engine-* directory, or None."""
    for sp in search_paths:
        try:
            for entry in sp.iterdir():
                if entry.is_dir() and entry.name.startswith("engine-"):
                    return entry, entry.name.removeprefix("engine-")
        except OSError:
            continue
    return None


def load_engine(ctx: EngineLoadContext):
    """Find and load an Engine for the given platform.

    Args:
        ctx: EngineLoadContext with platform, search_paths, profile,
             output_dir, and optional api_key / on_progress.

    Returns:
        Engine instance.

    Raises:
        FileNotFoundError: No Engine directory found in search_paths.
        ImportError: Engine package exists but cannot be imported.
    """
    resolved = ctx.platform or DEFAULT_PLATFORM
    engine_dir = find_engine_dir(ctx.search_paths, resolved)
    _ensure_engine_dependencies(engine_dir)
    pkg = _load_engine_package(engine_dir, resolved)
    return pkg.Engine(
        profile=ctx.profile,
        output_dir=ctx.output_dir,
        api_key=ctx.api_key,
        on_progress=ctx.on_progress,
    )


def _load_engine_package(engine_dir: Path, platform: str):
    """Import an engine package from engine_dir, falling back to pip site-packages."""
    root = str(engine_dir)
    if root not in sys.path:
        sys.path.insert(0, root)

    pkg_name = f"engine_{platform}"
    pkg = _exec_from_dir(engine_dir, pkg_name)
    if pkg is None:
        try:
            pkg = importlib.import_module(pkg_name)
        except ImportError:
            raise ImportError(
                f"Engine package '{pkg_name}' found at {engine_dir} but "
                f"cannot be imported. Check requirements: pip install -r "
                f"{engine_dir / 'requirements.txt'}"
            ) from None
    return pkg


def _exec_from_dir(engine_dir: Path, pkg_name: str):
    """Exec the package __init__.py from a local clone; None on failure."""
    spec = importlib.util.spec_from_file_location(
        pkg_name, engine_dir / pkg_name / "__init__.py"
    )
    if spec is None:
        return None
    try:
        pkg = importlib.util.module_from_spec(spec)
        sys.modules[pkg_name] = pkg
        spec.loader.exec_module(pkg)
        return pkg
    except Exception:
        return None


def copy_standby_profiles(
    platform: str, generator_root: Path | None = None, media_type: str | None = None
) -> int:
    """Copy standby YAML profiles from engine package to Generator's 02.STANDBY/.

    The engine owns the STANDBY shelf: every load syncs the engine's
    standby profiles over the shelf, filtered by the Generator's media type
    (Image Generator → IMG, Video Generator → VID). Users activate a
    profile by copying it into 03.PROFILES/ — the shelf itself is not
    user-edited.

    Args:
        platform: Engine platform name (e.g. 'replicate').
        generator_root: Generator project root.  Defaults to two levels above this file.
        media_type: 'IMG' or 'VID' shelf to seed. None seeds everything
            (engines without category shelves).

    Returns:
        Number of profile files copied.
    """
    if generator_root is None:
        generator_root = Path(__file__).resolve().parent.parent

    try:
        pkg = importlib.import_module(f"engine_{platform}")
    except ImportError:
        return 0

    profile_files: list[Path] = []
    if hasattr(pkg, "list_standby_profiles"):
        try:
            profile_files = pkg.list_standby_profiles(media_type)
        except TypeError:
            profile_files = pkg.list_standby_profiles()
    else:
        source = Path(pkg.__file__).parent / "profiles" / "standby"
        if source.is_dir():
            profile_files = sorted(source.glob("*.yaml"))

    if not profile_files:
        return 0

    dest = generator_root / "USER-FILES" / "02.STANDBY"
    dest.mkdir(parents=True, exist_ok=True)

    count = 0
    for yaml_file in profile_files:
        shutil.copy2(str(yaml_file), str(dest / yaml_file.name))
        count += 1

    return count
