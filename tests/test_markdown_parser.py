"""Tests for markdown_parser module."""

from unittest.mock import patch

import pytest

from src.processing.markdown_parser import (
    parse_markdown,
    read_markdown,
    validate_image_urls,
)


class TestParseMarkdown:
    def test_single_line_prompt(self):
        content = "A man walks on the beach.\n![start](https://example.com/frame.jpg)"
        prompt, urls, frames, duration, references = parse_markdown(content)
        assert prompt == "A man walks on the beach."
        assert urls == ["https://example.com/frame.jpg"]
        assert frames is None
        assert duration is None
        assert references == {}

    def test_first_non_empty_line(self):
        content = "\n\nHello world\n![img](https://x.com/a.jpg)"
        prompt, _, _, _, _ = parse_markdown(content)
        assert prompt == "Hello world"

    def test_leading_media_embed_is_ignored_bookmark(self):
        content = "![generated](../05.OUTPUT/prev.mp4)\nA real prompt"
        prompt, urls, _, _, _ = parse_markdown(content)
        assert prompt == "A real prompt"
        assert urls == []

    def test_remote_leading_embed_is_ignored_bookmark(self):
        content = (
            "![start](https://x.com/a.jpg)\nA real prompt\n![ref](https://x.com/ref.jpg)"
        )
        prompt, urls, _, _, _ = parse_markdown(content)
        assert prompt == "A real prompt"
        assert urls == ["https://x.com/ref.jpg"]

    def test_empty_content_raises(self):
        with pytest.raises(ValueError, match="No prompt"):
            parse_markdown("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError):
            parse_markdown("   \n   \n")

    def test_multiple_urls(self):
        content = "Prompt\n![a](https://example.com/1.jpg)\n![b](https://example.com/2.jpg)"
        _, urls, _, _, _ = parse_markdown(content)
        assert urls == ["https://example.com/1.jpg", "https://example.com/2.jpg"]

    def test_frames_extracted(self):
        content = "Prompt\n![a](https://example.com/1.jpg)\nframes: 96"
        _, _, frames, _, _ = parse_markdown(content)
        assert frames == 96

    def test_frames_case_insensitive(self):
        content = "Prompt\nFRAMES: 60"
        _, _, frames, _, _ = parse_markdown(content)
        assert frames == 60

    def test_format_warning_for_missing_bang(self):
        warnings: list[str] = []
        content = "Prompt\n[alt](https://example.com/1.jpg)"
        _, urls, _, _, _ = parse_markdown(content, warn=warnings.append)
        assert urls == []
        assert any("missing '!'" in w for w in warnings)

    def test_duration_integer(self):
        content = "Prompt\nduration: 5"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 5

    def test_duration_token_verbatim(self):
        content = "Prompt\nduration: auto"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == "auto"

    def test_duration_negative_one_is_int(self):
        content = "Prompt\nduration: -1"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == -1

    def test_duration_and_frames_both_parsed(self):
        content = "Prompt\nframes: 96\nduration: auto"
        _, _, frames, duration, _ = parse_markdown(content)
        assert frames == 96
        assert duration == "auto"

    def test_duration_case_insensitive(self):
        content = "Prompt\nDURATION: 8"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 8

    def test_named_slot_routed_when_declared(self):
        content = "Prompt\n![reference_images](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["reference_images"]
        )
        assert urls == []
        assert references == {"reference_images": ["https://example.com/1.jpg"]}

    def test_empty_alt_stays_primary_with_schema(self):
        content = "Prompt\n![](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["reference_images"]
        )
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}

    def test_unknown_alt_defaults_to_primary_with_warning(self):
        content = "Prompt\n![foo](https://example.com/1.jpg)"
        warnings: list[str] = []
        _, urls, _, _, references = parse_markdown(
            content,
            warn=warnings.append,
            declared_slots=["reference_images"],
        )
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}
        assert any("Unknown reference slot 'foo'" in w for w in warnings)

    def test_media_kind_alt_defaults_to_primary_silently(self):
        content = "Prompt\n![video](https://example.com/1.jpg)"
        warnings: list[str] = []
        _, urls, _, _, references = parse_markdown(
            content,
            warn=warnings.append,
            declared_slots=["reference_image_uri", "alpha_uri"],
            primary_slot="source_uri",
        )
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}
        assert warnings == []

    def test_primary_slot_name_alt_routes_to_primary(self):
        content = "Prompt\n![image](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["audio"], primary_slot="image"
        )
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}

    def test_custom_primary_slot_name_alt_routes_to_primary(self):
        content = "Prompt\n![start_image](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["end_image"], primary_slot="start_image"
        )
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}

    def test_primary_slot_name_not_stolen_from_declared(self):
        content = "Prompt\n![audio](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["audio"], primary_slot="image"
        )
        assert urls == []
        assert references == {"audio": ["https://example.com/1.jpg"]}

    def test_named_alt_falls_back_to_primary_without_schema(self):
        content = "Prompt\n![reference_images](https://example.com/1.jpg)"
        _, urls, _, _, references = parse_markdown(content)
        assert urls == ["https://example.com/1.jpg"]
        assert references == {}

    def test_multi_url_same_slot_appends(self):
        content = (
            "Prompt\n![reference_images](https://example.com/1.jpg)\n"
            "![reference_images](https://example.com/2.jpg)"
        )
        _, _, _, _, references = parse_markdown(content, declared_slots=["reference_images"])
        assert references == {
            "reference_images": [
                "https://example.com/1.jpg",
                "https://example.com/2.jpg",
            ]
        }


    def test_html_comment_line_ignored(self):
        content = (
            "Prompt\n"
            "<!-- ![audio](https://example.com/dead.wav) -->\n"
            "![image](https://example.com/live.jpg)"
        )
        _, urls, _, _, references = parse_markdown(
            content, declared_slots=["audio"], primary_slot="image"
        )
        assert urls == ["https://example.com/live.jpg"]
        assert references == {}

    def test_html_comment_block_ignored(self):
        content = (
            "Prompt\n"
            "<!--\n"
            "![audio](https://example.com/dead.wav)\n"
            "Duration: 99\n"
            "-->\n"
            "Duration: 7"
        )
        _, _, _, duration, references = parse_markdown(
            content, declared_slots=["audio"], primary_slot="image"
        )
        assert duration == 7
        assert references == {}

    def test_inline_html_comment_stripped(self):
        content = "A man walks <!-- this part is hidden --> on the beach."
        prompt, _, _, _, _ = parse_markdown(content)
        assert prompt == "A man walks  on the beach."

    def test_unclosed_html_comment_ignores_to_eof(self):
        content = "Prompt\n<!-- ![audio](https://example.com/a.wav)\n"
        warnings: list[str] = []
        _, _, _, _, references = parse_markdown(
            content, warn=warnings.append, declared_slots=["audio"]
        )
        assert references == {}
        assert any("Unclosed HTML comment" in w for w in warnings)

    def test_commented_out_whole_markdown_raises(self):
        content = "<!--\nPrompt\n![image](https://example.com/a.jpg)\n-->"
        with pytest.raises(ValueError, match="No prompt"):
            parse_markdown(content)


class TestFencedPromptShape:
    """The ```prompt fence: every line to the closing ```, newlines kept."""

    def test_fenced_single_line_prompt(self):
        content = "```prompt\nA man walks on the beach.\n```\n![img](https://example.com/frame.jpg)"
        prompt, urls, frames, duration, references = parse_markdown(content)
        assert prompt == "A man walks on the beach."
        assert urls == ["https://example.com/frame.jpg"]
        assert frames is None
        assert duration is None
        assert references == {}

    def test_fenced_multi_line_prompt_keeps_newlines(self):
        content = "```prompt\nLine one.\nLine two.\n```\n"
        prompt, *_ = parse_markdown(content)
        assert prompt == "Line one.\nLine two."

    def test_fenced_prompt_after_shape1_render_bookmark(self):
        content = (
            "![260407-abc-1](../../02_RW_GEN_IMG/run/260407-abc-1.png)\n"
            "\n"
            "```prompt\n"
            "A man walks on the beach.\n"
            "```\n"
            "![img](https://example.com/frame.jpg)"
        )
        prompt, urls, _, _, _ = parse_markdown(content)
        assert prompt == "A man walks on the beach."
        assert urls == ["https://example.com/frame.jpg"]

    def test_fenced_prompt_content_is_opaque(self):
        content = (
            "```prompt\n"
            "[not a link](https://example.com/x.jpg)\n"
            "duration: 99\n"
            "![ref](https://example.com/ref.jpg)\n"
            "```\n"
            "duration: 4\n"
        )
        warnings: list[str] = []
        prompt, urls, frames, duration, references = parse_markdown(
            content, warn=warnings.append, declared_slots=["reference_images"]
        )
        assert prompt == (
            "[not a link](https://example.com/x.jpg)\n"
            "duration: 99\n"
            "![ref](https://example.com/ref.jpg)"
        )
        assert urls == []
        assert frames is None
        assert duration == 4
        assert references == {}
        assert warnings == []

    def test_fenced_prompt_with_ref_line_after(self):
        content = "```prompt\nA man walks.\n```\n![ref](https://example.com/ref.jpg)\n"
        prompt, urls, _, _, references = parse_markdown(
            content, declared_slots=["reference_images"]
        )
        assert prompt == "A man walks."
        assert urls == []
        assert references == {"reference_images": ["https://example.com/ref.jpg"]}

    def test_fenced_prompt_with_legacy_duration_line(self):
        content = "```prompt\nA man.\n```\nduration: 6\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 6

    def test_unclosed_prompt_fence_takes_rest_and_warns(self):
        content = "```prompt\nA man walks.\n![img](https://example.com/frame.jpg)\n"
        warnings: list[str] = []
        prompt, urls, _, _, _ = parse_markdown(content, warn=warnings.append)
        assert prompt == "A man walks.\n![img](https://example.com/frame.jpg)"
        assert urls == []
        assert any("unclosed" in w for w in warnings)

    def test_empty_prompt_fence_raises(self):
        with pytest.raises(ValueError, match="No prompt"):
            parse_markdown("```prompt\n```\n")


class TestFencedDurationShape:
    """The ```duration fence: first non-empty line inside, same coercion."""

    def test_fenced_duration_integer(self):
        content = "Prompt\n```duration\n8\n```\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 8

    def test_fenced_duration_token_verbatim(self):
        content = "Prompt\n```duration\nauto\n```\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == "auto"

    def test_fenced_duration_negative_one_is_int(self):
        content = "Prompt\n```duration\n-1\n```\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == -1

    def test_fenced_duration_first_non_empty_line_wins(self):
        content = "Prompt\n```duration\n\n7\n9\n```\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 7

    def test_fenced_duration_after_fenced_prompt(self):
        content = "```prompt\nA man.\n```\n```duration\n12\n```\n![img](https://example.com/f.jpg)"
        prompt, urls, _, duration, _ = parse_markdown(content)
        assert prompt == "A man."
        assert duration == 12
        assert urls == ["https://example.com/f.jpg"]

    def test_fenced_duration_content_is_opaque(self):
        content = "Prompt\n```duration\n6\n[alt](https://example.com/x.jpg)\n```\n"
        warnings: list[str] = []
        _, urls, _, duration, _ = parse_markdown(content, warn=warnings.append)
        assert duration == 6
        assert urls == []
        assert warnings == []

    def test_legacy_duration_line_wins_when_first(self):
        content = "Prompt\nduration: 3\n```duration\n9\n```\n"
        _, _, _, duration, _ = parse_markdown(content)
        assert duration == 3

    def test_unclosed_duration_fence_reads_first_line_and_warns(self):
        content = "Prompt\n```duration\n4\n"
        warnings: list[str] = []
        _, _, _, duration, _ = parse_markdown(content, warn=warnings.append)
        assert duration == 4
        assert any("unclosed" in w for w in warnings)


class TestImgRefAliases:
    """`img` → primary (silent); `ref` → reference_images; mixing is rejected."""

    def test_img_alt_routes_to_primary_without_warning(self):
        content = "Prompt\n![img](https://example.com/frame.jpg)"
        warnings: list[str] = []
        _, urls, _, _, references = parse_markdown(
            content, warn=warnings.append, declared_slots=["reference_images"]
        )
        assert urls == ["https://example.com/frame.jpg"]
        assert references == {}
        assert warnings == []

    def test_ref_alt_routes_to_reference_images_slot(self):
        content = "Prompt\n![ref](https://example.com/ref.jpg)"
        _, urls, _, _, references = parse_markdown(content, declared_slots=["reference_images"])
        assert urls == []
        assert references == {"reference_images": ["https://example.com/ref.jpg"]}

    def test_ref_alt_falls_back_to_primary_when_slot_undeclared(self):
        content = "Prompt\n![ref](https://example.com/ref.jpg)"
        warnings: list[str] = []
        _, urls, _, _, references = parse_markdown(
            content, warn=warnings.append, declared_slots=["audio"]
        )
        assert urls == ["https://example.com/ref.jpg"]
        assert references == {}
        assert any("defaulting to primary" in w for w in warnings)

    def test_img_and_ref_mix_rejected(self):
        content = (
            "Prompt\n![img](https://example.com/frame.jpg)\n![ref](https://example.com/ref.jpg)\n"
        )
        with pytest.raises(ValueError, match="reference_images"):
            parse_markdown(content, declared_slots=["reference_images"])

    def test_img_and_ref_without_declared_slot_no_conflict(self):
        content = (
            "Prompt\n![img](https://example.com/frame.jpg)\n![ref](https://example.com/ref.jpg)"
        )
        _, urls, _, _, references = parse_markdown(content, declared_slots=["audio"])
        assert urls == ["https://example.com/frame.jpg", "https://example.com/ref.jpg"]
        assert references == {}

    def test_mix_rejection_also_for_slot_name_and_primary_alias(self):
        content = (
            "Prompt\n"
            "![image](https://example.com/frame.jpg)\n"
            "![reference_images](https://example.com/ref.jpg)"
        )
        with pytest.raises(ValueError, match="reference_images"):
            parse_markdown(content, declared_slots=["reference_images"])

    def test_unknown_alt_still_warns_and_goes_primary(self):
        content = "Prompt\n![foo](https://example.com/x.jpg)"
        warnings: list[str] = []
        _, urls, _, _, references = parse_markdown(
            content, warn=warnings.append, declared_slots=["reference_images"]
        )
        assert urls == ["https://example.com/x.jpg"]
        assert references == {}
        assert any("Unknown reference slot 'foo'" in w for w in warnings)

    def test_read_markdown_fenced_shapes(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text(
            "```prompt\nA man walks.\n```\n```duration\n9\n```\n![img](https://example.com/f.jpg)\n"
        )
        markdown_files = read_markdown(tmp_path, dry_run=True)
        assert len(markdown_files) == 1
        assert markdown_files[0]["prompt"] == "A man walks."
        assert markdown_files[0]["duration"] == 9
        assert markdown_files[0]["reference_urls"] == ["https://example.com/f.jpg"]

    def test_read_markdown_rejects_img_ref_mix(self, tmp_path):
        (tmp_path / "mix.md").write_text(
            "Prompt\n![img](https://example.com/frame.jpg)\n![ref](https://example.com/ref.jpg)\n"
        )
        (tmp_path / "ok.md").write_text("Good prompt\n")
        markdown_files = read_markdown(tmp_path, dry_run=True, declared_slots=["reference_images"])
        assert [m["path"].name for m in markdown_files] == ["ok.md"]


class TestStudioMarksBlock:
    """The IDE's trailing `studio:` cull-marks block is skipped whole."""

    _BLOCK = (
        "---\n"
        "studio:\n"
        "  marks:\n"
        "    rating: 3\n"
        "    colors: [green, red]\n"
        '    emoji: ["\U0001f600", "\U0001f4a9"]\n'
        "---\n"
    )

    def test_block_skipped_matches_blockless_file(self):
        base = "A detective in a dim office\n![](https://example.com/a.jpg)\n"
        warnings: list[str] = []
        with_block = parse_markdown(base + "\n" + self._BLOCK, warn=warnings.append)
        without_block = parse_markdown(base)
        assert with_block == without_block
        assert warnings == []

    def test_block_is_never_a_url_or_prompt(self):
        content = "Prompt\n" + self._BLOCK
        prompt, urls, frames, duration, references = parse_markdown(content)
        assert prompt == "Prompt"
        assert urls == []
        assert frames is None
        assert duration is None
        assert references == {}

    def test_extra_and_unknown_children_skipped(self):
        content = (
            "Prompt\n"
            "---\n"
            "studio:\n"
            "  marks:\n"
            "    rating: 5\n"
            "  timecode: 00:00:12\n"
            "  future_key: [a, b, c]\n"
            "---\n"
        )
        warnings: list[str] = []
        prompt, urls, _, _, _ = parse_markdown(content, warn=warnings.append)
        assert prompt == "Prompt"
        assert urls == []
        assert warnings == []

    def test_malformed_yaml_inside_block_skipped_without_crash(self):
        content = (
            "Prompt\n"
            "---\n"
            "studio:\n"
            "  marks:\n"
            "    rating: 3\n"
            "   colors: [unclosed\n"
            "  : : :\n"
            "---\n"
        )
        warnings: list[str] = []
        prompt, urls, _, _, _ = parse_markdown(content, warn=warnings.append)
        assert prompt == "Prompt"
        assert urls == []
        assert warnings == []

    def test_duration_and_frames_around_block_unchanged(self):
        content = "Prompt\nframes: 96\nduration: auto\n" + self._BLOCK
        _, _, frames, duration, _ = parse_markdown(content)
        assert frames == 96
        assert duration == "auto"

    def test_non_studio_trailing_fence_keeps_today_behaviour(self):
        content = (
            "Prompt\n"
            "---\n"
            "other_namespace:\n"
            "  ref: ![a](https://example.com/a.jpg)\n"
            "---\n"
        )
        _, urls, _, _, references = parse_markdown(content)
        assert urls == ["https://example.com/a.jpg"]
        assert references == {}

    def test_block_without_prompt_raises(self):
        with pytest.raises(ValueError, match="No prompt"):
            parse_markdown(self._BLOCK)

    def test_inline_studio_root_key_skipped(self):
        content = "Prompt\n---\nstudio: {marks: {rating: 1}}\n---\n"
        prompt, urls, _, _, _ = parse_markdown(content)
        assert prompt == "Prompt"
        assert urls == []

    def test_read_markdown_strips_block(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text(
            "Prompt\n"
            "duration: 7\n"
            "![](https://example.com/frame.jpg)\n"
            "\n"
            "---\n"
            "studio:\n"
            "  marks:\n"
            "    rating: 2\n"
            "---\n"
        )
        markdown_files = read_markdown(tmp_path, dry_run=True)
        assert len(markdown_files) == 1
        assert markdown_files[0]["duration"] == 7
        assert markdown_files[0]["reference_urls"] == ["https://example.com/frame.jpg"]


class TestValidateImageUrls:
    def test_split_valid_invalid(self):
        class FakeResp:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("src.processing.markdown_parser.urllib.request.urlopen") as mock_open:
            mock_open.side_effect = [FakeResp(), ValueError("down")]
            valid, invalid = validate_image_urls(["https://a.com/1.jpg", "https://b.com/2.jpg"])
            assert valid == ["https://a.com/1.jpg"]
            assert invalid == ["https://b.com/2.jpg"]


class TestReadMarkdown:
    def test_empty_dir_returns_empty_list(self, tmp_path):
        markdown_files = read_markdown(tmp_path)
        assert markdown_files == []

    def test_dry_run_skips_head_validation(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text("Prompt\n![a](https://example.com/frame.jpg)\n")
        with patch("src.processing.markdown_parser.validate_image_urls") as mock_validate:
            markdown_files = read_markdown(tmp_path, dry_run=True)
            mock_validate.assert_not_called()
        assert len(markdown_files) == 1
        assert markdown_files[0]["reference_urls"] == ["https://example.com/frame.jpg"]

    def test_nested_markdown_files_found(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "b.md").write_text("Nested prompt\n")
        markdown_files = read_markdown(tmp_path, dry_run=True)
        assert len(markdown_files) == 1
        assert markdown_files[0]["path"].name == "b.md"

    def test_parse_failure_rejects_markdown(self, tmp_path):
        (tmp_path / "bad.md").write_text("![only](https://example.com/a.jpg)\n")
        (tmp_path / "good.md").write_text("Good prompt\n")
        markdown_files = read_markdown(tmp_path, dry_run=True)
        assert len(markdown_files) == 1
        assert markdown_files[0]["prompt"] == "Good prompt"

    def test_all_rejected_returns_empty(self, tmp_path):
        (tmp_path / "bad.md").write_text("![only](https://example.com/a.jpg)\n")
        assert read_markdown(tmp_path, dry_run=True) == []

    def test_unreachable_primary_url_rejects_markdown(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text("Prompt\n![](https://example.com/frame.jpg)\n")
        with patch(
            "src.processing.markdown_parser.validate_image_urls",
            return_value=([], ["https://example.com/frame.jpg"]),
        ):
            markdown_files = read_markdown(tmp_path, dry_run=False)
        assert markdown_files == []

    def test_unreachable_named_slot_url_rejects_markdown(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text(
            "Prompt\n"
            "![](https://example.com/frame.jpg)\n"
            "![audio](https://example.com/dead.wav)\n"
        )
        with patch(
            "src.processing.markdown_parser.validate_image_urls",
            return_value=(["https://example.com/frame.jpg"], ["https://example.com/dead.wav"]),
        ):
            markdown_files = read_markdown(tmp_path, dry_run=False, declared_slots=["audio"])
        assert markdown_files == []

    def test_reachable_media_keeps_markdown(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text(
            "Prompt\n"
            "![](https://example.com/frame.jpg)\n"
            "![audio](https://example.com/music.wav)\n"
        )
        with patch(
            "src.processing.markdown_parser.validate_image_urls",
            return_value=(
                ["https://example.com/frame.jpg", "https://example.com/music.wav"],
                [],
            ),
        ):
            markdown_files = read_markdown(tmp_path, dry_run=False, declared_slots=["audio"])
        assert len(markdown_files) == 1
        assert markdown_files[0]["reference_urls"] == ["https://example.com/frame.jpg"]
        assert markdown_files[0]["references"] == {"audio": ["https://example.com/music.wav"]}

    def test_declared_slots_passed_to_parser(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text("Prompt\n![reference_images](https://example.com/frame.jpg)\n")
        markdown_files = read_markdown(tmp_path, dry_run=True, declared_slots=["reference_images"])
        assert markdown_files[0]["reference_urls"] == []
        assert markdown_files[0]["references"] == {
            "reference_images": ["https://example.com/frame.jpg"]
        }

    def test_primary_slot_passed_to_parser(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text("Prompt\n![start_image](https://example.com/frame.jpg)\n")
        markdown_files = read_markdown(
            tmp_path, dry_run=True, declared_slots=["end_image"], primary_slot="start_image"
        )
        assert markdown_files[0]["reference_urls"] == ["https://example.com/frame.jpg"]
        assert markdown_files[0]["references"] == {}

    def test_duration_and_references_in_markdown(self, tmp_path):
        markdown = tmp_path / "b.md"
        markdown.write_text("Prompt\nduration: auto\n![](https://example.com/frame.jpg)\n")
        markdown_files = read_markdown(tmp_path, dry_run=True)
        assert markdown_files[0]["duration"] == "auto"
        assert markdown_files[0]["reference_urls"] == ["https://example.com/frame.jpg"]
