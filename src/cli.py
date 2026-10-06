"""Command line interface argument parsing."""

import argparse

_ARGUMENTS: list[dict] = [
    {
        "flags": ["--input_dir"],
        "kwargs": {"type": str, "default": None, "help": "Source folder with .md files"},
    },
    {
        "flags": ["--output_dir"],
        "kwargs": {"type": str, "default": None, "help": "Target folder for generated output"},
    },
    {
        "flags": ["--profile"],
        "kwargs": {"type": str, "default": None, "help": "Profile YAML path"},
    },
    {
        "flags": ["--platform"],
        "kwargs": {
            "type": str,
            "default": None,
            "help": "Engine platform (overrides profile YAML)",
        },
    },
    {
        "flags": ["--dry-run"],
        "kwargs": {"action": "store_true", "help": "Test without making API calls"},
    },
    {
        "flags": ["--debug"],
        "kwargs": {"action": "store_true", "help": "Enable debug output"},
    },
    {
        "flags": ["--verbose"],
        "kwargs": {"action": "store_true", "help": "Enable verbose (INFO level) output"},
    },
    {
        "flags": ["-l", "--logs"],
        "kwargs": {
            "action": "store_true",
            "help": "Write run logs beside generated files (standalone only; default off)",
        },
    },
    {
        "flags": ["--cost-estimation"],
        "kwargs": {"action": "store_true", "help": "Estimate costs without generating"},
    },
    {
        "flags": ["--no-save-payloads"],
        "kwargs": {
            "action": "store_false",
            "dest": "save_payloads",
            "help": "Disable saving JSON payloads for each request",
        },
    },
    {
        "flags": ["--install-default-engine"],
        "kwargs": {
            "type": str,
            "default": None,
            "help": "Auto-install default Engine on first run "
            "(supported: replicate, fal, openrouter, google)",
        },
    },
]


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Video Generator — Video Generation"
    )
    parser.set_defaults(save_payloads=True)

    for arg in _ARGUMENTS:
        parser.add_argument(*arg["flags"], **arg["kwargs"])

    return parser.parse_args()
