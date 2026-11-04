"""Wiring tests: save-event stamping, end-of-run fallback, and the CLI switch."""

import json
import struct
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from src import main_verbose
from src.cli import parse_args
from src.main_verbose import _execute_pipeline, _resolve_input_for_event
from src.processing.payload_containers import has_xmp, read_xmp


def _box(box_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def _mp4() -> bytes:
    return _box(b"ftyp", b"isom") + _box(b"moov", b"\x00" * 8) + _box(b"mdat", b"data")


def _md(path: str, prompt: str = "a clip") -> dict:
    return {
        "path": Path(path),
        "prompt": prompt,
        "reference_urls": [],
        "frames": None,
        "duration": None,
        "references": {},
    }


def _profile(**overrides) -> dict:
    profile = {
        "profile_name": "test",
        "profile_path": "/profiles/test.yaml",
        "endpoint": "test/model",
        "parameters": {"fps": 24, "duration": 5.0},
        "prompt_prefix": "",
        "prompt_suffix": "",
        "duration_param_name": "duration",
    }
    profile.update(overrides)
    return profile


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


class StagingEngine:
    """Mimics engine-fal's stage → announce → reveal save protocol."""

    PROVIDER_NAME = "Stub"
    _on_progress = None

    def __init__(
        self,
        output_dir: Path,
        *,
        data: bytes | None = None,
        emit_save: bool = True,
        duration: int = 6,
    ) -> None:
        self.output_dir = output_dir
        self.data = _mp4() if data is None else data
        self.emit_save = emit_save
        self.duration = duration
        self.observed: list[tuple[bool, bool, bool]] = []

    def run(self, inputs: list) -> list[SimpleNamespace]:
        results = []
        for index, item in enumerate(inputs):
            dest = self.output_dir / f"{index}-{item.path.stem}.mp4"
            temp = self.output_dir / f".{dest.name}.part"
            temp.write_bytes(self.data)
            api_payload = {"prompt": item.prompt, "duration": self.duration}
            if self.emit_save and self._on_progress:
                self._on_progress(
                    SimpleNamespace(
                        message=f"💾 Saved: {dest.name}",
                        current=index + 1,
                        total=len(inputs),
                        saved_path=temp,
                        final_path=dest,
                        api_payload=api_payload,
                    )
                )
                self.observed.append((temp.exists(), has_xmp(temp), dest.exists()))
            temp.replace(dest)
            results.append(
                SimpleNamespace(
                    status="ok",
                    source_path=item.path,
                    path=dest,
                    error_msg="",
                    metadata={"api_payload": api_payload},
                )
            )
        return results


def test_stamps_the_staged_part_before_the_rename(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StagingEngine(tmp_path)

    exit_code = _execute_pipeline(
        [_md("in/a.md", "a castle")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
    )

    assert exit_code == 0
    # The .part existed, already carried XMP, and the final name was not visible.
    assert engine.observed == [(True, True, False)]
    payload = json.loads(read_xmp(tmp_path / "0-a.mp4") or "{}")
    assert payload["prompt"]["raw"] == "a castle"
    assert payload["media_type"] == "video"
    assert payload["video_duration"] == 6
    assert payload["output_file"] == "0-a.mp4"


def test_no_save_payloads_disables_stamping(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StagingEngine(tmp_path)
    observed: list[bool] = []

    original_run = engine.run

    def _run(inputs: list) -> list[SimpleNamespace]:
        results = original_run(inputs)
        observed.extend(has_xmp(p) for p in tmp_path.glob("*.mp4"))
        return results

    engine.run = _run  # type: ignore[method-assign]

    exit_code = _execute_pipeline(
        [_md("in/a.md")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
        save_payloads=False,
    )

    assert exit_code == 0
    assert observed == [False]
    assert read_xmp(tmp_path / "0-a.mp4") is None


def test_end_of_run_fallback_stamps_a_file_without_a_save_event(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StagingEngine(tmp_path, emit_save=False, duration=4)

    exit_code = _execute_pipeline(
        [_md("in/a.md", "a castle")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
    )

    assert exit_code == 0
    assert engine.observed == []
    payload = json.loads(read_xmp(tmp_path / "0-a.mp4") or "{}")
    assert payload["video_duration"] == 4


def test_a_stamp_failure_never_fails_the_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StagingEngine(tmp_path, data=b"\x00")

    exit_code = _execute_pipeline(
        [_md("in/a.md")],
        engine,
        "replicate",
        _profile(),
        tmp_path,
        Path("in"),
    )

    assert exit_code == 0
    assert (tmp_path / "0-a.mp4").exists()
    assert has_xmp(tmp_path / "0-a.mp4") is False


def test_prompt_match_wins_over_a_stale_current_index() -> None:
    profile = _profile()
    inputs = [
        SimpleNamespace(path=Path("in/a.md"), prompt="first"),
        SimpleNamespace(path=Path("in/b.md"), prompt="second"),
    ]
    msg = SimpleNamespace(current=1, api_payload={"prompt": "second"})

    assert _resolve_input_for_event(msg, inputs, profile) is inputs[1]


def test_unknown_prompt_returns_none_for_the_end_of_run_pass() -> None:
    profile = _profile()
    inputs = [SimpleNamespace(path=Path("in/a.md"), prompt="first")]
    msg = SimpleNamespace(current=1, api_payload={"prompt": "something else"})

    assert _resolve_input_for_event(msg, inputs, profile) is None


def test_out_of_bounds_current_returns_none() -> None:
    profile = _profile()
    inputs = [SimpleNamespace(path=Path("in/a.md"), prompt="first")]

    assert _resolve_input_for_event(SimpleNamespace(current=9), inputs, profile) is None


def test_no_api_payload_falls_back_to_current() -> None:
    profile = _profile()
    inputs = [SimpleNamespace(path=Path("in/a.md"), prompt="first")]

    assert _resolve_input_for_event(SimpleNamespace(current=1), inputs, profile) is inputs[0]


def test_cli_defaults_to_saving_payloads(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", ["prog"])
    assert parse_args().save_payloads is True

    monkeypatch.setattr(sys, "argv", ["prog", "--no-save-payloads"])
    assert parse_args().save_payloads is False


def test_studiolot_threads_save_payloads_and_keeps_it_out_of_parameters(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, object] = {}

    def _recorder(*args: object, **kwargs: object) -> int:
        captured["save_payloads"] = kwargs.get("save_payloads")
        captured["profile"] = args[3]
        return 0

    monkeypatch.setattr(main_verbose, "_execute_pipeline", _recorder)
    monkeypatch.setattr(
        main_verbose,
        "load_profile_studiolot",
        lambda _path: _profile(parameters={"fps": 24, "save_payloads": True}),
    )
    monkeypatch.setattr(
        main_verbose, "read_markdown", lambda *a, **k: [_md("in/a.md")]
    )
    monkeypatch.setattr(main_verbose, "get_api_key", lambda _platform: "key")
    monkeypatch.setattr(
        main_verbose, "_resolve_engine_for_studiolot", lambda *a, **k: StagingEngine
    )

    args = SimpleNamespace(
        profile="p.yaml",
        input_dir="in",
        output_dir=str(tmp_path),
        platform=None,
        dry_run=False,
        cost_estimation=False,
        save_payloads=False,
        install_default_engine=None,
        logs=False,
    )

    assert main_verbose._run_studiolot(args) == 0
    assert captured["save_payloads"] is False
    assert "save_payloads" not in captured["profile"]["parameters"]
