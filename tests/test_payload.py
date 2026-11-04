"""Tests for the schema-1 recipe payload (parity with image-generator)."""

import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

from src.constants import __version__
from src.processing.payload import compose_payload, payload_text


class _Item:
    def __init__(
        self,
        path: Path,
        prompt: str,
        reference_urls: list[str] | None = None,
        metadata: dict | None = None,
    ) -> None:
        self.path = path
        self.prompt = prompt
        self.reference_urls = reference_urls or []
        self.metadata = metadata or {}


def _engine() -> SimpleNamespace:
    return SimpleNamespace(PROVIDER_NAME="Fal.ai")


def _profile(**overrides) -> dict:
    profile = {
        "endpoint": "fal-ai/model",
        "parameters": {"duration": "5", "fps": 24, "save_payloads": False},
        "prompt_prefix": "A ",
        "prompt_suffix": " in motion.",
        "duration_param_name": "duration",
    }
    profile.update(overrides)
    return profile


def _compose(
    *,
    item: _Item | None = None,
    final_path: Path | None = None,
    profile: dict | None = None,
    input_root: Path | None = Path("/inputs"),
    api_payload: dict | None = None,
) -> dict:
    return compose_payload(
        item=item or _Item(Path("/inputs/sub/a.md"), "castle"),
        final_path=final_path or Path("/out/0001-a.mp4"),
        profile=profile or _profile(),
        platform="fal",
        engine=_engine(),
        input_root=input_root,
        api_payload=api_payload,
    )


def test_required_keys_match_schema_one() -> None:
    payload = _compose()

    assert set(payload) == {
        "schema",
        "generated_at",
        "generator",
        "engine",
        "endpoint",
        "parameters",
        "prompt",
        "prefix",
        "suffix",
        "reference_urls",
        "input_file",
        "media_type",
        "video_duration",
        "output_file",
    }
    assert payload["schema"] == 1
    assert payload["media_type"] == "video"
    assert payload["generator"] == {"name": "video-generator", "version": __version__}
    assert payload["engine"] == {"platform": "fal", "provider": "Fal.ai"}
    assert payload["endpoint"] == "fal-ai/model"
    assert payload["output_file"] == "0001-a.mp4"


def test_generated_at_is_utc_isoformat() -> None:
    payload = _compose()

    parsed = datetime.fromisoformat(payload["generated_at"])
    assert parsed.utcoffset() is not None
    assert payload["generated_at"].endswith("+00:00")


def test_prompt_wrapped_matches_prefix_and_suffix() -> None:
    payload = _compose(item=_Item(Path("/inputs/a.md"), "a castle"))

    assert payload["prompt"] == {
        "raw": "a castle",
        "wrapped": "A a castle in motion.",
    }
    assert payload["prefix"] == "A "
    assert payload["suffix"] == " in motion."


def test_wrapped_prompt_is_stripped() -> None:
    payload = _compose(profile=_profile(prompt_prefix="", prompt_suffix=""))

    assert payload["prompt"]["wrapped"] == "castle"


def test_parameters_exclude_generator_only_keys() -> None:
    payload = _compose()

    assert "save_payloads" not in payload["parameters"]
    assert payload["parameters"] == {"duration": "5", "fps": 24}


def test_input_file_is_relative_posix() -> None:
    payload = _compose(item=_Item(Path("/inputs/sub/deeper/a.md"), "castle"))

    assert payload["input_file"] == "sub/deeper/a.md"


def test_input_file_falls_back_to_the_filename_outside_the_root() -> None:
    payload = _compose(item=_Item(Path("/elsewhere/a.md"), "castle"))

    assert payload["input_file"] == "a.md"


def test_reference_urls_are_copied() -> None:
    payload = _compose(
        item=_Item(Path("/inputs/a.md"), "castle", ["https://example.com/a.png"])
    )

    assert payload["reference_urls"] == ["https://example.com/a.png"]


def test_preset_reference_urls_only_when_declared() -> None:
    assert "preset_reference_urls" not in _compose()

    payload = _compose(
        profile=_profile(reference_images=["https://example.com/preset.png"])
    )
    assert payload["preset_reference_urls"] == ["https://example.com/preset.png"]


def test_video_duration_prefers_the_provider_payload() -> None:
    payload = _compose(
        item=_Item(Path("/inputs/a.md"), "castle", metadata={"duration": 5}),
        api_payload={"prompt": "castle", "duration": 8},
    )

    assert payload["video_duration"] == 8


def test_video_duration_falls_back_to_input_metadata() -> None:
    payload = _compose(
        item=_Item(Path("/inputs/a.md"), "castle", metadata={"duration": 5}),
    )

    assert payload["video_duration"] == 5


def test_video_duration_keeps_tokens_verbatim() -> None:
    payload = _compose(
        item=_Item(Path("/inputs/a.md"), "castle", metadata={"duration": "auto"}),
    )

    assert payload["video_duration"] == "auto"


def test_video_duration_honours_a_custom_param_name() -> None:
    payload = _compose(
        profile=_profile(duration_param_name="clip_length"),
        api_payload={"clip_length": 7},
    )

    assert payload["video_duration"] == 7


def test_never_carries_the_empty_image_value() -> None:
    payload = _compose(
        item=_Item(Path("/inputs/a.md"), "castle", metadata={"duration": 5})
    )

    assert payload["video_duration"] != ""


def test_payload_text_is_indented_json() -> None:
    text = payload_text(
        item=_Item(Path("/inputs/a.md"), "castle", metadata={"duration": 5}),
        final_path=Path("/out/a.mp4"),
        profile=_profile(),
        platform="fal",
        engine=_engine(),
        input_root=Path("/inputs"),
    )

    assert json.loads(text)["schema"] == 1
    assert "\n  " in text
