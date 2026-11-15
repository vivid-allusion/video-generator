"""Tests for legacy profile normalization (params/fps/duration/image_url)."""

from src.processing.profiles import normalize_legacy_profile


def test_legacy_params_block_becomes_parameters():
    data = normalize_legacy_profile(
        {
            "Model": {"endpoint": "owner/model"},
            "params": {"aspect_ratio": "16:9", "negative_prompt": "grain"},
            "fps": 24,
            "duration_min": 5,
        }
    )
    assert data["parameters"]["aspect_ratio"] == "16:9"
    assert data["parameters"]["negative_prompt"] == "grain"


def test_legacy_top_level_fps_promoted():
    data = normalize_legacy_profile({"params": {}, "fps": 30})
    assert data["parameters"]["fps"] == 30


def test_legacy_duration_min_becomes_default_duration_int():
    data = normalize_legacy_profile({"params": {}, "duration_min": 5})
    assert data["parameters"]["duration"] == 5
    assert isinstance(data["parameters"]["duration"], int)


def test_legacy_image_url_becomes_image_url_param():
    data = normalize_legacy_profile({"image_url": "start_image"})
    assert data["image_url_param"] == "start_image"


def test_legacy_model_endpoint_extracted():
    data = normalize_legacy_profile({"Model": {"endpoint": "owner/model"}})
    assert data["endpoint"] == "owner/model"
    assert data["platform"] == "replicate"
    assert data["media_type"] == "video"


def test_modern_parameters_preserved():
    data = normalize_legacy_profile(
        {
            "endpoint": "owner/model",
            "parameters": {"fps": 24, "duration": 10},
        }
    )
    assert data["parameters"] == {"fps": 24, "duration": 10}


def test_modern_parameters_win_over_legacy_params():
    data = normalize_legacy_profile(
        {
            "params": {"aspect_ratio": "1:1"},
            "parameters": {"fps": 24, "aspect_ratio": "16:9"},
        }
    )
    assert data["parameters"]["aspect_ratio"] == "16:9"


def test_duration_config_fps_still_used():
    data = normalize_legacy_profile({"duration_config": {"fps": 25}})
    assert data["parameters"]["fps"] == 25


def test_parameters_fps_injected_when_missing():
    data = normalize_legacy_profile({"endpoint": "owner/model"})
    assert data["parameters"]["fps"] == 24


def test_profile_has_prompt_text():
    from src.processing.profiles import profile_has_prompt_text

    assert profile_has_prompt_text({"prompt_prefix": "a"})
    assert profile_has_prompt_text({"prompt_suffix": " b "})
    assert not profile_has_prompt_text({"prompt_prefix": " ", "prompt_suffix": None})
