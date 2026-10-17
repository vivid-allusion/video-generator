"""Authentication module — 4-tier env var hierarchy.

Priority:
    1. Already-set env var (injected by OpenReel TUI or cloud wrapper)
    2. pass show studiolot/<key> (GPG-encrypted, optional)
    3. .env file in project root (standalone mode)
    4. Hard exit if no key found
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

from loguru import logger

from ..constants import DEFAULT_PLATFORM
from ..exceptions import AuthenticationError

_PLATFORM_KEY_MAP: dict[str, str] = {
    "replicate": "REPLICATE_API_TOKEN",
    "fal": "FAL_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "google": "GOOGLE_API_KEY",
    "beeble": "BEEBLE_API_KEY",
    "evolink": "EVOLINK_API_KEY",
    "spicyapi": "SPICYAPI_API_KEY",
}

PASS_STORE_PREFIX: str = "studiolot/"

SUPPORTED_PLATFORMS: list[str] = list(_PLATFORM_KEY_MAP.keys())


def _key_name(platform: str) -> str:
    return _PLATFORM_KEY_MAP.get(platform, f"{platform.upper()}_API_KEY")


def _try_pass(key_name: str) -> str | None:
    try:
        result = subprocess.run(
            ["pass", "show", f"{PASS_STORE_PREFIX}{key_name}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            logger.info("Retrieved {} from pass", key_name)
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return None


def get_api_key(platform: str = DEFAULT_PLATFORM) -> str:
    required_key = _key_name(platform)

    api_token = os.getenv(required_key)
    if api_token:
        logger.info("Using {} from environment", required_key)
        return api_token

    api_token = _try_pass(required_key.lower())
    if api_token:
        os.environ[required_key] = api_token
        return api_token

    from .env import get_api_token_from_env

    api_token = get_api_token_from_env(required_key)
    if api_token:
        return api_token

    raise AuthenticationError(
        f"No API key found. Set {required_key} as an env var, in pass, or in .env.\n"
        f"  - Set as env var  (export {required_key}=...)\n"
        f"  - Store in pass   (pass insert {PASS_STORE_PREFIX}{required_key.lower()})\n"
        f"  - Add to .env     (echo {required_key}=... > .env)"
    )


# ── interactive wizard ────────────────────────────────────────────────────────


def _prompt_platform() -> str:
    """Prompt user to select a platform from the supported list."""
    print("\nAvailable platforms:")
    for i, p in enumerate(SUPPORTED_PLATFORMS, 1):
        print(f"  {i}. {p}")
    while True:
        try:
            choice = input(
                f"Choose platform [1-{len(SUPPORTED_PLATFORMS)}]: "
            ).strip()
            idx = int(choice) - 1
            if 0 <= idx < len(SUPPORTED_PLATFORMS):
                return SUPPORTED_PLATFORMS[idx]
        except (ValueError, IndexError):
            pass
        print(f"Invalid choice. Enter 1-{len(SUPPORTED_PLATFORMS)}.")


def _prompt_and_save_key(platform: str) -> str:
    """Prompt for API key, persist to .env, return the key."""
    key_name = _key_name(platform)
    env_path = Path(__file__).resolve().parent.parent.parent / ".env"

    msg = (
        f"\nNo API key found for '{platform}' ({key_name}).\n"
        f"Key will be saved to {env_path} — do not commit this file.\n"
        f"Paste {key_name}: "
    )
    api_key = input(msg).strip()
    if not api_key:
        logger.error("No API key provided.")
        sys.exit(1)

    env_path.parent.mkdir(parents=True, exist_ok=True)
    with open(env_path, "a") as f:
        f.write(f"\n{key_name}={api_key}\n")
    os.environ[key_name] = api_key
    logger.success(f"Saved {key_name} to {env_path}")
    return api_key


def _offer_engine_install(platform: str) -> None:
    """Check if engine package is installed; install if missing."""
    spec = importlib.util.find_spec(f"engine_{platform}")
    if spec is not None:
        return

    print(f"\nEngine '{platform}' is not installed. Installing...")
    from ..engine_helpers import auto_install_engine

    if not auto_install_engine(platform):
        print(f"\nInstall failed. Install manually:\n"
              f"  git clone https://github.com/vivid-allusion/engine-{platform}.git "
              f"ENGINES/engine-{platform}/\n"
              f"  pip install -r ENGINES/engine-{platform}/requirements.txt\n")
        sys.exit(1)


def get_api_key_interactive() -> tuple[str, str]:
    """Interactive wizard: engine selection + API key provisioning.

    Returns (platform, api_key).  Exits if stdin is not a TTY.
    """
    if not sys.stdin.isatty():
        raise AuthenticationError(
            "No API key found. Run interactively (python3 run.py) for guided setup."
        )

    platform = _prompt_platform()
    _offer_engine_install(platform)
    api_key = _prompt_and_save_key(platform)
    return platform, api_key


__all__ = ["get_api_key", "get_api_key_interactive", "SUPPORTED_PLATFORMS"]
