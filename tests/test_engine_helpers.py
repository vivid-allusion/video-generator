"""Tests for build_inputs (verbatim-within-profile-bounds duration, references,
Q20 warning) and cost-estimation duration fallback (Q18)."""

import types
from pathlib import Path
from unittest.mock import patch

import pytest

from src.engine_helpers import build_inputs, clamp_duration
from src.exceptions import ConfigurationError
from src.main_verbose import _markdown_duration


class FakeInputFile:
    def __init__(self, *, path, prompt, reference_urls, metadata, references=None):
        self.path = path
        self.prompt = prompt
        self.reference_urls = reference_urls
        self.metadata = metadata
        self.references = references or {}


class OldInputFile:
    def __init__(self, *, path, prompt, reference_urls, metadata):
        self.path = path
        self.prompt = prompt
        self.reference_urls = reference_urls
        self.metadata = metadata


def _fake_module(cls):
    return types.SimpleNamespace(InputFile=cls)


def _patched_engine(cls):
    return patch(
        "src.engine_helpers.importlib.import_module",
        return_value=_fake_module(cls),
    )


def _markdown(**overrides):
    base = {
        "path": Path("a.md"),
        "prompt": "p",
        "reference_urls": [],
        "frames": None,
        "duration": None,
        "references": {},
    }
    base.update(overrides)
    return base


PROFILE = {"parameters": {"fps": 24, "duration": 5.0}}

BOUNDED_PROFILE = {
    "parameters": {"fps": 24, "duration": 5.0},
    "duration_min": 4,
    "duration_max": 30,
}


class TestBuildInputsMetadata:
    def test_duration_integer_verbatim(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=5)], "replicate", profile=PROFILE)
        assert inputs[0].metadata["duration"] == 5

    def test_duration_token_verbatim(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs(
                [_markdown(duration="auto")], "replicate", profile=PROFILE
            )
        assert inputs[0].metadata["duration"] == "auto"

    def test_duration_wins_over_frames(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs(
                [_markdown(frames=96, duration="auto")], "replicate", profile=PROFILE
            )
        assert inputs[0].metadata["duration"] == "auto"

    def test_frames_converted_via_fps(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(frames=48)], "replicate", profile=PROFILE)
        assert inputs[0].metadata["duration"] == 2.0

    def test_profile_default_when_nothing_given(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown()], "replicate", profile=PROFILE)
        assert inputs[0].metadata["duration"] == 5.0


class TestBuildInputsDurationBounds:
    """Top-level profile `duration_min`/`duration_max` clamp the effective duration."""

    def test_below_min_clamps_up(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=2)], "replicate", profile=BOUNDED_PROFILE)
        assert inputs[0].metadata["duration"] == 4

    def test_above_max_clamps_down(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=40)], "replicate", profile=BOUNDED_PROFILE)
        assert inputs[0].metadata["duration"] == 30

    def test_within_bounds_unchanged(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=5)], "replicate", profile=BOUNDED_PROFILE)
        assert inputs[0].metadata["duration"] == 5

    def test_token_passes_through_verbatim(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs(
                [_markdown(duration="auto")], "replicate", profile=BOUNDED_PROFILE
            )
        assert inputs[0].metadata["duration"] == "auto"

    def test_negative_sentinel_passes_through_verbatim(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=-1)], "replicate", profile=BOUNDED_PROFILE)
        assert inputs[0].metadata["duration"] == -1

    def test_no_bounds_leaves_duration_unchanged(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=2)], "replicate", profile=PROFILE)
        assert inputs[0].metadata["duration"] == 2

    def test_frames_derived_duration_clamped(self):
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(frames=48)], "replicate", profile=BOUNDED_PROFILE)
        assert inputs[0].metadata["duration"] == 4

    def test_profile_default_clamped(self):
        profile = {
            "parameters": {"fps": 24, "duration": 2},
            "duration_min": 4,
            "duration_max": 30,
        }
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown()], "replicate", profile=profile)
        assert inputs[0].metadata["duration"] == 4

    def test_min_only_bound_leaves_high_values(self):
        profile = {"parameters": {"fps": 24, "duration": 5.0}, "duration_min": 4}
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=40)], "replicate", profile=profile)
        assert inputs[0].metadata["duration"] == 40

    def test_max_only_bound_leaves_low_values(self):
        profile = {"parameters": {"fps": 24, "duration": 5.0}, "duration_max": 30}
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([_markdown(duration=2)], "replicate", profile=profile)
        assert inputs[0].metadata["duration"] == 2


class TestClampDuration:
    def test_string_token_passes_through(self):
        assert clamp_duration("auto", 4, 30) == "auto"

    def test_negative_sentinel_passes_through(self):
        assert clamp_duration(-1, 4, 30) == -1

    def test_none_bounds_leave_value_unchanged(self):
        assert clamp_duration(2, None, None) == 2


class TestBuildInputsReferences:
    def test_references_passed_to_supporting_engine(self):
        markdown = _markdown(references={"reference_images": ["https://x.com/a.jpg"]})
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([markdown], "replicate", profile=PROFILE)
        assert inputs[0].references == {"reference_images": ["https://x.com/a.jpg"]}

    def test_no_warning_when_engine_supports_references(self):
        with patch("src.engine_helpers.logger") as mock_logger, _patched_engine(
            FakeInputFile
        ):
            build_inputs([_markdown()], "replicate", profile=PROFILE)
        mock_logger.warning.assert_not_called()

    def test_warning_when_old_engine_drops_named_slots(self):
        markdown = _markdown(references={"reference_images": ["https://x.com/a.jpg"]})
        with patch("src.engine_helpers.logger") as mock_logger, _patched_engine(
            OldInputFile
        ):
            inputs = build_inputs([markdown], "replicate", profile=PROFILE)
        assert len(inputs) == 1
        mock_logger.warning.assert_called_once()

    def test_old_engine_without_named_refs_stays_silent(self):
        with patch("src.engine_helpers.logger") as mock_logger, _patched_engine(
            OldInputFile
        ):
            build_inputs([_markdown()], "replicate", profile=PROFILE)
        mock_logger.warning.assert_not_called()


class TestBuildInputsPresetReferenceImages:
    """The profile's top-level `reference_images` merge (GENERATOR_CONTRACT §2f)."""

    PRESET_REFS = ["https://x.com/preset-1.jpg", "https://x.com/preset-2.jpg"]

    def _profile(self, **overrides):
        base = {"parameters": {"fps": 24, "duration": 5.0}}
        base.update(overrides)
        return base

    def test_declared_slot_appends_preset_refs_after_own(self):
        markdown = _markdown(
            reference_urls=["https://x.com/primary.jpg"],
            references={"reference_images": ["https://x.com/own.jpg"]},
        )
        profile = self._profile(
            slots=["reference_images"], reference_images=self.PRESET_REFS
        )
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([markdown], "replicate", profile=profile)
        assert inputs[0].references["reference_images"] == [
            "https://x.com/own.jpg",
            *self.PRESET_REFS,
        ]
        assert inputs[0].reference_urls == ["https://x.com/primary.jpg"]

    def test_no_declared_slot_appends_preset_refs_to_reference_urls(self):
        markdown = _markdown(reference_urls=["https://x.com/primary.jpg"])
        profile = self._profile(reference_images=["https://x.com/preset-1.jpg"])
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([markdown], "replicate", profile=profile)
        assert inputs[0].reference_urls == [
            "https://x.com/primary.jpg",
            "https://x.com/preset-1.jpg",
        ]
        assert inputs[0].references == {}

    def test_preset_refs_merge_into_every_input(self):
        profile = self._profile(reference_images=["https://x.com/preset-1.jpg"])
        markdowns = [
            _markdown(path=Path("a.md"), reference_urls=["https://x.com/a.jpg"]),
            _markdown(path=Path("b.md"), reference_urls=["https://x.com/b.jpg"]),
        ]
        with _patched_engine(FakeInputFile):
            inputs = build_inputs(markdowns, "replicate", profile=profile)
        assert inputs[0].reference_urls == [
            "https://x.com/a.jpg",
            "https://x.com/preset-1.jpg",
        ]
        assert inputs[1].reference_urls == [
            "https://x.com/b.jpg",
            "https://x.com/preset-1.jpg",
        ]

    def test_absent_preset_refs_leave_inputs_unchanged(self):
        markdown = _markdown(reference_urls=["https://x.com/primary.jpg"])
        with _patched_engine(FakeInputFile):
            inputs = build_inputs([markdown], "replicate", profile=PROFILE)
        assert inputs[0].reference_urls == ["https://x.com/primary.jpg"]
        assert inputs[0].references == {}

    def test_old_engine_with_preset_refs_warns_and_falls_back(self):
        markdown = _markdown(reference_urls=["https://x.com/primary.jpg"])
        profile = self._profile(reference_images=["https://x.com/preset-1.jpg"])
        with patch("src.engine_helpers.logger") as mock_logger, _patched_engine(
            OldInputFile
        ):
            inputs = build_inputs([markdown], "replicate", profile=profile)
        assert inputs[0].reference_urls == [
            "https://x.com/primary.jpg",
            "https://x.com/preset-1.jpg",
        ]
        mock_logger.warning.assert_called_once()

    def test_declared_slot_with_old_engine_fails_loud(self):
        profile = self._profile(
            slots=["reference_images"], reference_images=["https://x.com/preset-1.jpg"]
        )
        with _patched_engine(OldInputFile):
            with pytest.raises(ConfigurationError):
                build_inputs([_markdown()], "replicate", profile=profile)


class TestMarkdownDurationCost:
    def test_numeric_duration_used(self):
        assert _markdown_duration(_markdown(duration=7), PROFILE) == 7.0

    def test_token_falls_back_to_profile_default(self):
        assert _markdown_duration(_markdown(duration="auto"), PROFILE) == 5.0

    def test_negative_one_falls_back(self):
        assert _markdown_duration(_markdown(duration=-1), PROFILE) == 5.0

    def test_frames_still_converted(self):
        assert _markdown_duration(_markdown(frames=48), PROFILE) == 2.0

    def test_nothing_falls_back_to_profile_default(self):
        assert _markdown_duration(_markdown(), PROFILE) == 5.0

    def test_estimate_clamps_to_min(self):
        assert _markdown_duration(_markdown(duration=2), BOUNDED_PROFILE) == 4.0

    def test_estimate_clamps_to_max(self):
        assert _markdown_duration(_markdown(duration=40), BOUNDED_PROFILE) == 30.0

    def test_estimate_within_bounds_unchanged(self):
        assert _markdown_duration(_markdown(duration=5), BOUNDED_PROFILE) == 5.0

    def test_estimate_no_bounds_unchanged(self):
        assert _markdown_duration(_markdown(duration=2), PROFILE) == 2.0

    def test_token_fallback_estimate_clamped(self):
        profile = {
            "parameters": {"fps": 24, "duration": 5.0},
            "duration_min": 6,
            "duration_max": 30,
        }
        assert _markdown_duration(_markdown(duration="auto"), profile) == 6.0
