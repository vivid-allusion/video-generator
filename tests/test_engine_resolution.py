"""Studiolot-mode engine resolution: project tree first, generator fallback."""

from pathlib import Path

import pytest

from src import main_verbose


class TestResolveEngineForStudiolot:
    def test_uses_project_engines_when_present(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        project = tmp_path / "00_APPLICATIONS" / "ENGINES"
        captured: dict[str, object] = {}

        monkeypatch.setattr(main_verbose, "find_project_engines_dir", lambda _d: project)

        def _recorder(ctx: object) -> str:
            captured["paths"] = ctx.search_paths
            return "ENGINE"

        monkeypatch.setattr(main_verbose, "load_engine", _recorder)

        result = main_verbose._resolve_engine_for_studiolot(
            tmp_path, "replicate", {}, "key"
        )

        assert result == "ENGINE"
        assert captured["paths"] == [project]

    def test_falls_back_to_generator_engines(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        fallback = Path("/fake/generator/ENGINES")
        captured: dict[str, object] = {}

        monkeypatch.setattr(main_verbose, "find_project_engines_dir", lambda _d: None)
        monkeypatch.setattr(main_verbose, "find_generator_engines_dir", lambda: fallback)

        def _recorder(ctx: object) -> str:
            captured["paths"] = ctx.search_paths
            return "ENGINE"

        monkeypatch.setattr(main_verbose, "load_engine", _recorder)

        result = main_verbose._resolve_engine_for_studiolot(
            tmp_path, "replicate", {}, "key"
        )

        assert result == "ENGINE"
        assert captured["paths"] == [fallback]
