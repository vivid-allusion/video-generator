"""Video Generator — Engine-based video generation generator.

Both studiolot and standalone modes share the same Engine-based execution.
The Generator reads video Markdown files, loads an Engine, and calls engine.run().

Per GENERATOR_CONTRACT.md §4d: InputFile.metadata carries {duration, fps}
from the profile YAML's parameters block.
"""

import os
import sys
from pathlib import Path
from typing import Any

from loguru import logger

from .auth import get_api_key, get_api_key_interactive
from .cli import parse_args
from .constants import DEFAULT_PLATFORM, __version__
from .datatypes import Markdown
from .engine_helpers import (
    build_inputs,
    find_project_engines_dir,
    make_engine_ctx,
)
from .engine_loader import load_engine
from .exceptions import (
    AuthenticationError,
    ConfigurationError,
    PreflightExit,
    ValidationError,
)
from .processing.first_run import handle_first_run
from .processing.markdown_parser import read_markdown
from .processing.profiles import (
    load_profile_standalone,
    load_profile_studiolot,
)
from .utils.logging import (
    log_file_only,
    setup_logging,
    start_output_capture,
    write_run_logs,
)
from .utils.path_resolver import (
    create_timestamped_output_path,
    resolve_input_path,
    resolve_output_base_path,
)

# ── CLI / orchestration helpers ────────────────────────────────────────────────


def _print_profile_guidance() -> None:
    """Pretty guidance for activating a profile after the first-run wizard."""
    from rich.console import Console
    from rich.text import Text

    root = Path(__file__).resolve().parent.parent
    standby = root / "USER-FILES" / "02.STANDBY"
    active = root / "USER-FILES" / "03.PROFILES"

    body = Text()
    body.append("Thanks for supplying your API key!\n", style="bold green")
    body.append("To make the script operational:\n", style="bold")
    body.append("  1. Pick a profile YAML from:\n", style="dim")
    body.append(f"     {standby}/\n", style="cyan")
    body.append("  2. Copy it to:\n", style="dim")
    body.append(f"     {active}/\n", style="cyan")
    body.append("  3. Re-run the script\n", style="dim")

    Console().print(body)



def _apply_cli_overrides(profile: dict[str, Any], args: Any) -> dict[str, Any]:
    """Return a copy of profile with CLI flags merged into parameters."""
    params = dict(profile.get("parameters", {}))
    if not args.save_payloads:
        params["save_payloads"] = False
    return {**profile, "parameters": params}


def _markdown_duration(markdown: Markdown, profile: dict[str, Any]) -> float:
    """Duration for a Markdown file: numeric `duration:` verbatim, else frames via
    fps, else profile default. Token durations (auto, -1) fall back to the
    profile default for cost estimation only."""
    params = profile.get("parameters", {})
    fps = float(params.get("fps", 24))
    profile_duration = float(params.get("duration", 5.0))
    raw = markdown.get("duration")
    if isinstance(raw, (int, float)) and raw > 0:
        return float(raw)
    if markdown["frames"]:
        return markdown["frames"] / fps
    return profile_duration


def _handle_preflight_checks(
    args: Any, markdown_files: list[Markdown], profile: dict[str, Any]
) -> None:
    if args.cost_estimation:
        cost_per_second = float(profile.get("pricing", {}).get("cost_per_second", 0.0))
        total = sum(_markdown_duration(b, profile) * cost_per_second for b in markdown_files)
        logger.info(
            f"Estimated cost: {len(markdown_files)} Markdown file(s), "
            f"{sum(_markdown_duration(b, profile) for b in markdown_files):.1f}s total "
            f"x ${cost_per_second:.4f}/s = ${total:.2f}"
        )
        raise PreflightExit(0)
    if args.dry_run:
        logger.info(f"DRY RUN -- would process {len(markdown_files)} Markdown file(s)")
        raise PreflightExit(0)


def _report_results(results: list[Any]) -> int:
    """Summarise engine.run() results and return exit code."""
    ok = sum(1 for r in results if r.status == "ok")
    failed = sum(1 for r in results if r.status == "error")
    sys.stderr.write(f"Complete: {ok} generated, {failed} errors\n")
    for r in results:
        if r.status == "error":
            logger.error(f"  {r.source_path.name}: {r.error_msg}")
    return 1 if failed else 0


def _logs_enabled(args: Any, run_mode: str) -> bool:
    """Run logs are opt-in (-l/--logs) and standalone-only."""
    return bool(getattr(args, "logs", False)) and run_mode == "standalone"


def _execute_pipeline(
    markdown_files: list[Markdown],
    engine: Any,
    platform: str,
    profile: dict[str, Any],
    output_dir: Path,
    input_root: Path | None = None,
    logs: bool = False,
) -> int:
    """Run the core generation pipeline: build inputs → run → report → log."""
    from rich.progress import (
        BarColumn,
        Progress,
        SpinnerColumn,
        TaskProgressColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    inputs = build_inputs(markdown_files, platform, input_root, profile)
    total = len(inputs)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
    ) as bar:
        task = bar.add_task("Processing...", total=total)

        def on_progress(msg: Any) -> None:
            text = msg.message if hasattr(msg, "message") else str(msg)
            bar.update(task, description=text)
            current = getattr(msg, "current", 0)
            if current:
                bar.update(task, completed=current)
            if getattr(msg, "level", "") == "error":
                logger.error(text)
            payload = getattr(msg, "api_payload", None)
            if logs and payload is not None:
                log_file_only(f"Payload: {payload}")

        original = engine._on_progress
        engine._on_progress = on_progress
        try:
            results = engine.run(inputs)
        finally:
            engine._on_progress = original

    exit_code = _report_results(results)
    generated = [
        r.path
        for r in results
        if r.status == "ok" and getattr(r, "path", None)
    ]
    if logs:
        write_run_logs(generated, output_dir)
    return exit_code


def _resolve_engine_for_studiolot(
    output_dir: Path,
    platform: str,
    profile: dict[str, Any],
    api_key: str | None,
) -> Any:
    project_engines = find_project_engines_dir(output_dir)
    if not project_engines:
        raise FileNotFoundError(
            "Engine directory not found. Expected 00_APPLICATIONS/ENGINES/ "
            "under the project root."
        )
    return load_engine(
        make_engine_ctx(platform, [project_engines], profile, output_dir, api_key)
    )


# ── entry point ────────────────────────────────────────────────────────────────


def main() -> int:
    args = parse_args()
    is_studiolot = bool(args.profile or args.input_dir or args.output_dir)
    run_mode = "studiolot" if is_studiolot else "standalone"
    if _logs_enabled(args, run_mode):
        start_output_capture()
    setup_logging(debug=args.debug, verbose=args.verbose)

    logger.debug("=" * 60)
    logger.debug(f"Video Generator — Video Generation v{__version__}")
    logger.debug("=" * 60)

    try:
        if is_studiolot:
            return _run_studiolot(args)
        else:
            return _run_standalone(args)
    except KeyboardInterrupt:
        logger.warning("Interrupted by user")
        return 130
    except PreflightExit as e:
        return e.exit_code
    except (AuthenticationError, ConfigurationError, ValidationError) as e:
        logger.error(f"Error: {e}")
        return 1
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        return 1


# ── run modes ──────────────────────────────────────────────────────────────────


def _run_studiolot(args) -> int:
    if not args.output_dir:
        raise ConfigurationError("--output_dir is required in studiolot mode")
    if not args.profile:
        raise ConfigurationError("--profile is required in studiolot mode")

    output_dir = Path(args.output_dir)
    profile_path = Path(args.profile)

    profile = load_profile_studiolot(profile_path)
    profile = _apply_cli_overrides(profile, args)
    platform = args.platform or profile.get("platform") or DEFAULT_PLATFORM
    profile["platform"] = platform

    input_dir = Path(args.input_dir) if args.input_dir else Path(".")

    markdown_files = read_markdown(
        input_dir,
        dry_run=args.dry_run,
        declared_slots=profile.get("slots"),
        primary_slot=profile.get("image_url_param") or "image",
    )
    if not markdown_files:
        if any(input_dir.rglob("*.md")):
            raise ValidationError(
                f"All Markdown files in {input_dir} were rejected — see errors above"
            )
        raise FileNotFoundError(f"No .md files found in {input_dir}")
    _handle_preflight_checks(args, markdown_files, profile)

    output_dir.mkdir(parents=True, exist_ok=True)

    api_key = get_api_key(platform)
    engine = _resolve_engine_for_studiolot(output_dir, platform, profile, api_key)

    return _execute_pipeline(
        markdown_files, engine, platform, profile, output_dir, input_dir, logs=False
    )


def _run_standalone(args) -> int:
    search_paths = [Path(__file__).resolve().parent.parent / "ENGINES"]
    platform = DEFAULT_PLATFORM

    auto_install = args.install_default_engine or os.environ.get(
        "STUDIOLOT_AUTO_INSTALL_ENGINE"
    )

    result = handle_first_run(platform, search_paths, args.dry_run, auto_install)
    if result is None:
        return 1
    platform, api_key = result

    try:
        profile = load_profile_standalone()
        platform = profile.get("platform") or platform
    except ConfigurationError:
        _print_profile_guidance()
        return 0

    profile = _apply_cli_overrides(profile, args)

    # ── check inputs before creating output dir ──────────────────────────────

    input_path, _ = resolve_input_path(profile)
    markdown_files = read_markdown(
        input_path,
        dry_run=args.dry_run,
        declared_slots=profile.get("slots"),
        primary_slot=profile.get("image_url_param") or "image",
    )
    _handle_preflight_checks(args, markdown_files, profile)

    if not markdown_files:
        if any(input_path.rglob("*.md")):
            logger.error(
                f"All Markdown files in {input_path} were rejected — nothing to process"
            )
            return 1
        logger.warning(
            f"No .md files to process. Add .md files to {input_path} and re-run."
        )
        return 0

    # ── output directory (only created when generation is confirmed) ────────

    output_base = resolve_output_base_path(profile)
    output_dir = create_timestamped_output_path(output_base)

    # ── API key (engine existed but wizard was skipped) ──────────────────────

    if not args.dry_run and api_key is None:
        try:
            api_key = get_api_key(platform)
        except AuthenticationError:
            if sys.stdin.isatty():
                platform, api_key = get_api_key_interactive()
                profile["platform"] = platform
            else:
                raise

    # ── engine with proper profile ───────────────────────────────────────────

    engine = load_engine(
        make_engine_ctx(platform, search_paths, profile, output_dir, api_key)
    )

    return _execute_pipeline(
        markdown_files,
        engine,
        platform,
        profile,
        output_dir,
        input_path,
        logs=_logs_enabled(args, "standalone"),
    )


if __name__ == "__main__":
    sys.exit(main())
