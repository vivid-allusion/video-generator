"""Land each clip in the output folder already stamped.

The engine saves into a hidden staging folder inside the output folder (same
disk, so the last step is one atomic rename). As each prompt's results come
back they are stamped and only then moved into place, keeping ``relative_dir``
subfolders. Once a file is visible in the output folder the run never touches
it again: the user may be editing it (flagging) while later prompts still run.
"""

import shutil
from collections.abc import Callable
from pathlib import Path
from typing import Any

STAGING = ".staging"


def _move(path: Path, src: Path, dst: Path) -> Path:
    target = dst / path.relative_to(src)
    if target != path:
        target.parent.mkdir(parents=True, exist_ok=True)
        path.replace(target)
    return target


def _land(result: Any, src: Path, dst: Path, stamp: Callable[[Any], None] | None) -> Any:
    """Stamp and move one result out of ``src``; results already out are left as is."""
    metadata = getattr(result, "metadata", None)
    log = metadata.get("error_log") if isinstance(metadata, dict) else None
    if log and Path(log).is_file() and Path(log).is_relative_to(src):
        metadata["error_log"] = str(_move(Path(log), src, dst))
    path = getattr(result, "path", None)
    if getattr(result, "status", "") != "ok" or not path or not Path(path).is_relative_to(src):
        return result
    if stamp is not None:
        stamp(result)
    result.path = _move(Path(path), src, dst)
    return result


def run_landed(
    engine: Any, inputs: list[Any], output_dir: Path, stamp: Callable[[Any], None] | None
) -> list[Any]:
    """``engine.run(inputs)`` with every clip landing finished as its prompt returns.

    An engine without ``_output_dir`` saves straight into the output folder; its
    clips are stamped in place once the run is over, as before.
    """
    if not hasattr(engine, "_output_dir"):
        results = engine.run(inputs)
        if stamp is not None:
            for result in results:
                if getattr(result, "status", "") == "ok" and getattr(result, "path", None):
                    stamp(result)
        return results
    staging = output_dir / STAGING
    original_dir = engine._output_dir
    run_one = getattr(engine, "_run_one", None)
    engine._output_dir = staging

    def land(result: Any) -> Any:
        return _land(result, staging, output_dir, stamp)

    if run_one is not None:
        # The serial loop and the batch runner both call _run_one, so wrapping it
        # lands each prompt while the others are still running.
        engine._run_one = lambda *a, **k: [land(r) for r in run_one(*a, **k)]
    try:
        # Skipped or crashed prompts never pass through _run_one.
        return [land(r) for r in engine.run(inputs)]
    finally:
        engine._output_dir = original_dir
        if run_one is not None:
            engine._run_one = run_one
        if staging.is_dir():
            for left in sorted(staging.rglob("*")):
                if left.is_file() and not left.name.endswith(".part"):
                    _move(left, staging, output_dir)
        shutil.rmtree(staging, ignore_errors=True)
