"""Setting blocks: ```resolution / ```aspect_ratio / ```audio, checked against the model."""

import json
from pathlib import Path

import pytest

from src.main_verbose import _execute_pipeline
from src.processing.markdown_parser import parse_markdown, read_markdown
from src.processing.payload_containers import read_xmp
from src.processing.setting_blocks import block_names, check_settings, model_settings
from tests.test_payload_wiring import StagingEngine, _install_stub_engine_module, _md, _profile

SEEDANCE = """endpoint = "seedance"
[params.duration]
type = "integer"
[params.ratio]
type = "select"
options = [{ value = "16:9" }, { value = "9:16" }]
[params.resolution]
type = "select"
options = [{ value = "720p" }, { value = "1080p" }]
[params.generate_audio]
type = "boolean"
"""
SEEDREAM = """endpoint = "seedream"
[params.size]
type = "text"
"""


@pytest.fixture
def engines(tmp_path: Path) -> Path:
    root = tmp_path / "ENGINES" / "engine-bytedance" / "engine_bytedance" / "endpoints"
    (root / "VID-Models").mkdir(parents=True)
    (root / "IMG-Models").mkdir(parents=True)
    (root / "VID-Models" / "seedance.toml").write_text(SEEDANCE)
    (root / "IMG-Models" / "seedream.toml").write_text(SEEDREAM)
    return tmp_path / "ENGINES"


def _model(engines: Path, endpoint: str = "seedance") -> tuple[dict, set[str]]:
    return model_settings("bytedance", endpoint, [engines])


def test_model_settings_reads_this_model_and_every_engine_name(engines: Path) -> None:
    model, known = _model(engines)
    assert set(model) == {"duration", "ratio", "resolution", "generate_audio"}
    assert "size" in known
    assert block_names(model, known) == {"resolution", "aspect_ratio", "audio", "size"}


def test_blocks_are_read_and_never_reach_the_prompt() -> None:
    settings: dict[str, str] = {}
    text = (
        "A heron lands.\n\n```resolution\n\n1080p\n```\n```aspect_ratio\n9:16\n```\n"
        "```audio\noff\n```\n```notes\nkeep this\n```\n"
    )
    prompt, *_ = parse_markdown(
        text, setting_names={"resolution", "aspect_ratio", "audio"}, settings=settings
    )
    assert prompt == "A heron lands."
    assert settings == {"resolution": "1080p", "aspect_ratio": "9:16", "audio": "off"}


def test_without_a_model_no_block_is_read() -> None:
    prompt, *_ = parse_markdown("A heron.\n```resolution\n8k\n```\n")
    assert prompt == "A heron."


def test_check_maps_blocks_to_the_models_own_names(engines: Path) -> None:
    model, _ = _model(engines)
    got = check_settings({"resolution": "1080p", "aspect_ratio": "9:16", "audio": "No"}, model)
    assert got == {"resolution": "1080p", "ratio": "9:16", "generate_audio": False}


@pytest.mark.parametrize(
    ("blocks", "words"),
    [
        ({"resolution": "8k"}, ("resolution", "8k")),
        ({"aspect_ratio": "4:3"}, ("aspect_ratio", "4:3")),
        ({"audio": "loud"}, ("audio", "loud")),
        ({"size": "1024x1024"}, ("size", "1024x1024")),
    ],
)
def test_check_refuses_what_the_model_lacks(
    engines: Path, blocks: dict[str, str], words: tuple[str, ...]
) -> None:
    model, _ = _model(engines)
    with pytest.raises(ValueError) as err:
        check_settings(blocks, model)
    assert all(w in str(err.value) for w in words)


def test_a_model_without_the_setting_refuses_the_block(engines: Path) -> None:
    model, _ = _model(engines, "seedream")
    with pytest.raises(ValueError, match="resolution"):
        check_settings({"resolution": "720p"}, model)


def test_read_markdown_rejects_bad_blocks_and_keeps_other_fences(
    engines: Path, tmp_path: Path
) -> None:
    inputs = tmp_path / "in"
    inputs.mkdir()
    (inputs / "a_ok.md").write_text("A fox.\n```resolution\n1080p\n```\n```json\n{}\n```\n")
    (inputs / "b_bad.md").write_text("An owl.\n```resolution\n8k\n```\n")
    (inputs / "c_size.md").write_text("A cat.\n```size\n1024x1024\n```\n")
    (inputs / "d_plain.md").write_text("A boat.\n")
    got = read_markdown(inputs, dry_run=True, model=_model(engines))
    assert [(m["path"].name, m["settings"]) for m in got] == [
        ("a_ok.md", {"resolution": "1080p"}),
        ("d_plain.md", {}),
    ]


def test_each_run_gets_its_own_settings_and_the_profile_is_restored(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _install_stub_engine_module(monkeypatch)
    engine = StagingEngine(tmp_path)
    profile = _profile(parameters={"duration": 5, "resolution": "720p"})
    seen: list[tuple[list[str], str]] = []
    original_run = engine.run

    def _run(inputs: list) -> list:
        seen.append(([i.path.stem for i in inputs], profile["parameters"]["resolution"]))
        return original_run(inputs)

    engine.run = _run  # type: ignore[method-assign]
    over = {**_md("in/b.md"), "settings": {"resolution": "1080p"}}
    exit_code = _execute_pipeline(
        [_md("in/a.md"), over, _md("in/c.md")], engine, "replicate", profile, tmp_path, Path("in")
    )
    assert exit_code == 0
    assert seen == [(["a", "c"], "720p"), (["b"], "1080p")]
    assert profile["parameters"] == {"duration": 5, "resolution": "720p"}
    stamped = json.loads(read_xmp(tmp_path / "0-b.mp4") or "{}")
    assert stamped["parameters"]["resolution"] == "1080p"
