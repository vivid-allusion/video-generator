from pathlib import Path

from src import main_verbose
from src.engine_helpers import find_generator_engines_dir, find_project_engines_dir


def test_finds_project_layout(tmp_path: Path) -> None:
    engines = tmp_path / ".00_TOOLS" / "GENERATORS" / "ENGINES"
    engines.mkdir(parents=True)
    out = tmp_path / "09_OUTPUT"
    out.mkdir()
    assert find_project_engines_dir(out) == engines.resolve()


def test_old_layout_is_not_found(tmp_path: Path) -> None:
    (tmp_path / "00_APPLICATIONS" / "ENGINES").mkdir(parents=True)
    assert find_project_engines_dir(tmp_path) is None


def test_falls_back_to_generator_engines(tmp_path: Path, monkeypatch) -> None:
    seen: list[list[Path]] = []
    monkeypatch.setattr(
        main_verbose, "load_engine", lambda ctx: seen.append(ctx.search_paths)
    )
    main_verbose._resolve_engine_for_studiolot(tmp_path, "fal", {}, None)
    assert seen == [[find_generator_engines_dir()]]
