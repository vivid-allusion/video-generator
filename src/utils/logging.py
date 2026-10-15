"""Logging setup with loguru + complete run-output capture.

Capture lets every generated file ship a full-run log beside it:
`<generated-file-stem>.log` mirrors the video name so runs are
traceable from the output directory alone.

On top of the opt-in run logs, a failed run always writes a run-level
`<YYMMDD_HHMMSS>_ERROR.log` — see `write_error_log()`.
"""

import io
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from loguru import logger

from ..constants import __version__

CONSOLE_FORMAT = (
    "<green>{time:HH:mm:ss}</green> | <level>{level: <8}</level> | "
    "<level>{message}</level>"
)

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*m")

_capture: io.StringIO | None = None

_file_only: list[str] = []


def log_file_only(message: str) -> None:
    """Record a message that goes into the run .log files, never the console."""
    ts = datetime.now().strftime("%H:%M:%S")
    _file_only.append(f"{ts} | INFO     | {message}")


class _TeeStream(io.TextIOBase):
    """Forward writes to the real stream while capturing a plain-text copy."""

    def __init__(self, target: io.TextIOBase) -> None:
        self._target = target

    def write(self, data: str) -> int:
        if _capture is not None:
            _capture.write(_ANSI_ESCAPE.sub("", data))
        return self._target.write(data)

    def flush(self) -> None:
        self._target.flush()

    def writable(self) -> bool:
        return True

    def isatty(self) -> bool:
        return self._target.isatty()

    def fileno(self) -> int:
        return self._target.fileno()

    @property
    def encoding(self) -> str:
        return getattr(self._target, "encoding", "utf-8")


def setup_logging(debug: bool = False, verbose: bool = False) -> None:
    """Configure console logging for the application."""
    logger.remove()

    level = "DEBUG" if debug else "INFO"
    logger.add(
        sys.stderr,
        format=CONSOLE_FORMAT,
        level=level,
        colorize=True,
    )

    logger.debug(f"Logging configured (debug={debug})")


def start_output_capture() -> None:
    """Tee stdout/stderr into a buffer so the full run output can be logged."""
    global _capture
    _capture = io.StringIO()
    sys.stdout = _TeeStream(sys.stdout)  # type: ignore[assignment]
    sys.stderr = _TeeStream(sys.stderr)  # type: ignore[assignment]


def captured_output() -> str:
    """Return everything written to stdout/stderr since capture started,
    plus file-only records (payloads etc. hidden from the console)."""
    base = _capture.getvalue() if _capture is not None else ""
    if not _file_only:
        return base
    return base + "\n".join(_file_only) + "\n"


def write_run_logs(generated_paths: list[Path], output_dir: Path) -> list[Path]:
    """Write one complete-run log per generated file, named after the file.

    Falls back to a single timestamped log in output_dir when nothing was
    generated, so failed runs still leave a debug trail.
    """
    text = captured_output()
    if generated_paths:
        written: list[Path] = []
        for gen_path in generated_paths:
            log_path = gen_path.with_suffix(".log")
            log_path.write_text(text)
            written.append(log_path)
        return written

    ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    log_path = output_dir / f"video_generator_{ts}.log"
    log_path.write_text(text)
    return [log_path]


def write_error_log(
    output_dir: Path,
    *,
    run_mode: str,
    profile_path: str | Path | None = None,
    input_root: str | Path | None = None,
    results: list[Any] | None = None,
    traceback_text: str | None = None,
) -> Path:
    """Write the run-level `<YYMMDD_HHMMSS>_ERROR.log` for a failed run.

    Unlike the opt-in per-file run logs, this one is always written when a
    run ends with at least one failed item or when `engine.run()` raises —
    a failed generation must leave a verbose trace, `--logs` or not. The
    per-item error logs (engine-written) are referenced by their paths.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    all_results = list(results or [])
    ok = sum(1 for r in all_results if getattr(r, "status", "") == "ok")
    failed = [r for r in all_results if getattr(r, "status", "") == "error"]

    lines = [
        f"Video Generator v{__version__} — run-level error log",
        f"when: {datetime.now().astimezone().isoformat()}",
        f"run mode: {run_mode}",
        f"profile: {profile_path if profile_path else 'n/a'}",
        f"input root: {input_root if input_root else 'n/a'}",
        f"counts: {ok} ok, {len(failed)} failed",
    ]
    for result in failed:
        source = getattr(result, "source_path", None)
        source_name = Path(source).name if source else "?"
        error_log = (getattr(result, "metadata", None) or {}).get("error_log")
        suffix = f" (error log: {error_log})" if error_log else ""
        lines.append(f"failed: {source_name} — {getattr(result, 'error_msg', '')}{suffix}")
    if traceback_text:
        lines.append("traceback:")
        lines.append(traceback_text.rstrip("\n"))
    lines.append(
        "note: Written automatically on a failed run — see the office/MEMORY "
        "error-log convention."
    )

    ts = datetime.now().strftime("%y%m%d_%H%M%S")
    log_path = output_dir / f"{ts}_ERROR.log"
    log_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return log_path
