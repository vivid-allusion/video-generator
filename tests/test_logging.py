"""Tests for opt-in (-l/--logs), standalone-only run logging (W32).

Default runs write no log; a standalone run opts back in with -l/--logs; a
driven (studiolot-mode) run never writes a log, even with the flag set.
"""

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src import main_verbose
from src.cli import parse_args
from src.exceptions import ValidationError
from src.main_verbose import _execute_pipeline, _logs_enabled
from src.utils.logging import start_output_capture, write_error_log


@pytest.fixture(autouse=True)
def _restore_streams():
    stdout, stderr = sys.stdout, sys.stderr
    yield
    sys.stdout, sys.stderr = stdout, stderr


def _md(path: str, prompt: str = "a clip") -> dict:
    return {
        "path": Path(path),
        "prompt": prompt,
        "reference_urls": [],
        "frames": None,
        "duration": None,
        "references": {},
    }


def _install_stub_engine_module(monkeypatch: pytest.MonkeyPatch) -> None:
    class InputFile:
        def __init__(
            self,
            *,
            path: Path,
            prompt: str,
            reference_urls: list,
            metadata: dict,
            references: dict | None = None,
        ) -> None:
            self.path = path
            self.prompt = prompt
            self.reference_urls = reference_urls
            self.metadata = metadata
            self.references = references or {}

    module = ModuleType("engine_replicate")
    module.InputFile = InputFile
    monkeypatch.setitem(sys.modules, "engine_replicate", module)


class StubEngine:
    PROVIDER_NAME = "Stub"
    _on_progress = None

    def __init__(self, output_dir: Path) -> None:
        self.output_dir = output_dir

    def run(self, inputs: list) -> list[SimpleNamespace]:
        results = []
        for index, item in enumerate(inputs):
            out = self.output_dir / f"{index}-{item.path.stem}.mp4"
            out.write_bytes(b"\x00")
            results.append(
                SimpleNamespace(status="ok", source_path=item.path, path=out)
            )
        return results


def _profile() -> dict:
    return {
        "profile_name": "test",
        "profile_path": "/profiles/test.yaml",
        "endpoint": "test/model",
        "parameters": {"fps": 24, "duration": 5.0},
        "pricing": {"cost_per_second": 0.1},
        "prompt_prefix": "",
        "prompt_suffix": "",
    }


def test_execute_pipeline_default_writes_no_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StubEngine(tmp_path)

    exit_code = _execute_pipeline(
        [_md("in/a.md")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
        logs=False,
    )

    assert exit_code == 0
    assert list(tmp_path.glob("*.log")) == []
    assert (tmp_path / "0-a.mp4").exists()


def test_execute_pipeline_logs_flag_writes_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StubEngine(tmp_path)
    start_output_capture()

    exit_code = _execute_pipeline(
        [_md("in/a.md")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
        logs=True,
    )

    assert exit_code == 0
    log_path = tmp_path / "0-a.log"
    assert log_path.exists()
    assert "Complete:" in log_path.read_text()


class TestLogsFlag:
    def test_parse_args_default_logs_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["prog"])
        assert parse_args().logs is False

    def test_parse_args_l_short_and_long(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for flag in ("-l", "--logs"):
            monkeypatch.setattr(sys, "argv", ["prog", flag])
            assert parse_args().logs is True

    @pytest.mark.parametrize(
        ("flag", "run_mode", "expected"),
        [
            (True, "standalone", True),
            (False, "standalone", False),
            (True, "studiolot", False),
            (False, "studiolot", False),
        ],
    )
    def test_logs_enabled_is_standalone_only(
        self, flag: bool, run_mode: str, expected: bool
    ) -> None:
        assert _logs_enabled(SimpleNamespace(logs=flag), run_mode) is expected

    def test_run_studiolot_passes_logs_false(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        captured: dict[str, object] = {}

        def _recorder(*args: object, **kwargs: object) -> int:
            captured["logs"] = kwargs.get("logs")
            return 0

        monkeypatch.setattr(main_verbose, "_execute_pipeline", _recorder)
        monkeypatch.setattr(
            main_verbose, "load_profile_studiolot", lambda _path: _profile()
        )
        monkeypatch.setattr(
            main_verbose, "read_markdown", lambda *a, **k: [_md("in/a.md")]
        )
        monkeypatch.setattr(main_verbose, "get_api_key", lambda _platform: "key")
        monkeypatch.setattr(
            main_verbose, "_resolve_engine_for_studiolot", lambda *a, **k: StubEngine
        )

        args = SimpleNamespace(
            profile="p.yaml",
            input_dir="in",
            output_dir=str(tmp_path),
            platform=None,
            dry_run=False,
            cost_estimation=False,
            save_payloads=True,
            install_default_engine=None,
            logs=True,
        )

        assert main_verbose._run_studiolot(args) == 0
        assert captured["logs"] is False


class FailingStubEngine(StubEngine):
    """One ok item plus one failed item carrying its per-item error-log path."""

    def run(self, inputs: list) -> list[SimpleNamespace]:
        results = super().run(inputs)
        results.append(
            SimpleNamespace(
                status="error",
                source_path=Path("in/bad.md"),
                path=None,
                error_msg="RuntimeError: API timeout",
                metadata={"error_log": "/out/999999_000000-0_ERROR.log"},
            )
        )
        return results


def test_failed_item_writes_run_level_error_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = FailingStubEngine(tmp_path)

    exit_code = _execute_pipeline(
        [_md("in/a.md")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
        logs=False,
    )

    assert exit_code == 1
    error_logs = list(tmp_path.glob("*_ERROR.log"))
    assert len(error_logs) == 1
    content = error_logs[0].read_text(encoding="utf-8")
    assert "Video Generator v" in content
    assert "run mode: standalone" in content
    assert "profile: /profiles/test.yaml" in content
    assert "input root: in" in content
    assert "counts: 1 ok, 1 failed" in content
    assert (
        "failed: bad.md — RuntimeError: API timeout "
        "(error log: /out/999999_000000-0_ERROR.log)" in content
    )
    # The opt-in per-file run log stays off; only the ERROR log is written.
    plain_logs = [p for p in tmp_path.glob("*.log") if p.name != error_logs[0].name]
    assert [p for p in plain_logs if not p.name.endswith("_ERROR.log")] == []


def test_raising_engine_writes_run_level_error_log_and_reraises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class RaisingEngine(StubEngine):
        def run(self, inputs: list) -> list[SimpleNamespace]:
            raise RuntimeError("provider exploded")

    _install_stub_engine_module(monkeypatch)
    engine = RaisingEngine(tmp_path)

    with pytest.raises(RuntimeError, match="provider exploded"):
        _execute_pipeline(
            [_md("in/a.md")],
            engine,
            "replicate",
            _profile(),
            tmp_path,
            Path("in"),
            logs=False,
        )

    error_logs = list(tmp_path.glob("*_ERROR.log"))
    assert len(error_logs) == 1
    content = error_logs[0].read_text(encoding="utf-8")
    assert "run mode: standalone" in content
    assert "counts: 0 ok, 0 failed" in content
    assert "Traceback (most recent call last):" in content
    assert "RuntimeError: provider exploded" in content


def test_write_error_log_names_file_with_timestamp(tmp_path: Path) -> None:
    log_path = write_error_log(
        tmp_path,
        run_mode="studiolot",
        profile_path="p.yaml",
        input_root=tmp_path,
    )
    assert log_path.parent == tmp_path
    stamp = log_path.name.removesuffix("_ERROR.log")
    assert len(stamp) == 13
    assert stamp[:6].isdigit() and stamp[7:13].isdigit()
    assert stamp[6] == "_"


def test_preflight_rejection_writes_no_error_log(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A parse/preflight rejection never reaches a generation attempt."""
    (tmp_path / "rejected.md").write_text("prompt", encoding="utf-8")
    monkeypatch.setattr(main_verbose, "load_profile_studiolot", lambda _path: _profile())
    monkeypatch.setattr(main_verbose, "read_markdown", lambda *a, **k: [])

    args = SimpleNamespace(
        profile="p.yaml",
        input_dir=str(tmp_path),
        output_dir=str(tmp_path),
        platform=None,
        dry_run=False,
        cost_estimation=False,
        save_payloads=True,
        install_default_engine=None,
        logs=True,
    )

    with pytest.raises(ValidationError):
        main_verbose._run_studiolot(args)
    assert list(tmp_path.glob("*_ERROR.log")) == []
