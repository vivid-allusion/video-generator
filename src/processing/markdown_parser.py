"""Markdown-file parsing for video generation.

Parses Markdown `.md` files and extracts:
- Text prompt: a plain first line, or the content of a ```prompt fence — every
  line up to the closing ``` becomes the prompt, newlines kept
- Reference URLs from markdown ![alt](URL) syntax — empty alt, `img` or the
  primary slot name feeds the primary slot; a declared named alt feeds the
  named slot. `ref`, `reference_images` and `reference_image_urls` all mean
  the row's declared reference-image slot. An unknown alt rejects the file,
  and so do two or more primary pictures
- Optional frame count from a `frames: N` line (deprecated, converted via fps)
- Optional raw duration from a `duration: <int|token>` line, or from the
  first non-empty line inside a ```duration fence (same coercion)
- Setting blocks (```resolution, ```aspect_ratio, ```audio, and any setting
  of the engine this model lacks): first non-empty line each, never the
  prompt, checked against the model (see setting_blocks)

A bullet carrying BOTH a primary URL (e.g. `img`) and reference-image URLs
(e.g. `ref`) is rejected at parse time — the model cannot combine a
first-frame image with reference images.

Fenced blocks are opaque: lines inside a ```prompt / ```duration fence are
never scanned for images, metadata, or format warnings.

HTML comments are ignored: anything between <!-- and --> (single-line,
inline, or spanning multiple lines) is stripped before parsing, so
commented-out prompts, images, or metadata never reach the payload.

A `---` block starting on line 1 and closed by the next `---` is front matter
(the IDE's marks, a Prompt Summary, anything). It is skipped whole — never a
prompt, never a URL, never a warning — whatever its keys. The old place, a
trailing `studio:` block, is refused.

A leading whole-line media embed — image or video, any target — is the
previous generation kept by tooling as a visual bookmark: it is skipped whole
(never the prompt, never a reference). References stay below the prompt.

Format:
    Line 1: Text prompt — a plain line or a ```prompt fence
    Lines 2+: ![alt](URL), frames: N, duration: <value> and/or a ```duration fence
    (optional) front matter on line 1, before the prompt
"""

import re
import sys
import textwrap
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger
from PIL import Image, ImageDraw, ImageFont

from ..datatypes import Markdown
from .setting_blocks import block_names, check_settings

if TYPE_CHECKING:
    from collections.abc import Callable, Collection

_FRAMES_RE = re.compile(r"^frames:\s*(\d+)", re.IGNORECASE)
_DURATION_RE = re.compile(r"^duration:\s*(\S+)", re.IGNORECASE)

_IMG_URL_PATTERN = re.compile(r"!\[([^\]]*)\]\((https?://[^\)]+)\)")
# A whole line that is nothing but a markdown media embed (image or video),
# any target — the previous-generation bookmark tooling writes above the
# prompt. A leading one is neither prompt nor media.
_MD_MEDIA_LINE = re.compile(r"!\[.*?\]\([^\s()]*(?:\([^\s()]*\)[^\s()]*)*\)")
_LINK_WITHOUT_BANG = re.compile(r"(?<!!)\[.*?\]\((https?://[^\)]+)\)")
_BANG_SPACE_PATTERN = re.compile(r"! +\[.*?\]\(.*?\)")
_PAREN_SPACE_PATTERN = re.compile(r"!\[.*?\] +\(.*?\)")
_SWAPPED_PATTERN = re.compile(r"!\[(https?://[^\]]+)\]\([^\)]+\)")
_UNCLOSED_PATTERN = re.compile(r"!\[.*?\]\([^\)]*$")
_HTML_IMG_PATTERN = re.compile(r"<img[^>]*src\s*=\s*['\"]([^'\"]+)['\"]", re.IGNORECASE)
_NON_HTTP_URL = re.compile(
    r"!\[.*?\]\((?!https?://)(\.\.?/|\.\.?\\|//|/|data:|file:|ftp:|[A-Za-z]:\\|\w+://)[^\)]+\)"
)
_HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)

_STUDIO_ROOT_RE = re.compile(r"^studio:(\s|$)")
_FENCE_RE = re.compile(r"^-{3,}$")

_PROMPT_FENCE_OPEN_RE = re.compile(r"^```\s*prompt\s*$", re.IGNORECASE)
_DURATION_FENCE_OPEN_RE = re.compile(r"^```\s*duration\s*$", re.IGNORECASE)
_FENCE_CLOSE_RE = re.compile(r"^```\s*$")
_NAMED_FENCE_RE = re.compile(r"^```\s*(\w+)\s*$")

_PRIMARY_ALIASES = {"video", "image", "source", "media", "src", "input", "img"}
# `ref`, `reference_images` and `reference_image_urls` all mean the row's
# reference-picture slot (Seedance 2.5 / MiniMax H3 / Oxen input_images); first declared wins.
_REF_SLOT_NAMES = ("reference_images", "reference_image_urls", "input_images")
_SLOT_ALIASES = {"ref": _REF_SLOT_NAMES, **{n: _REF_SLOT_NAMES for n in _REF_SLOT_NAMES}}


def _strip_front_matter(content: str) -> str:
    """Drop a `---` block that starts on line 1 and closes at the next `---`.

    Whatever its keys, the block is metadata, never prompt or media. An
    unclosed opener is left alone.
    """
    lines = content.split("\n")
    if not lines or not _FENCE_RE.match(lines[0].strip()):
        return content
    for end in range(1, len(lines)):
        if _FENCE_RE.match(lines[end].strip()):
            return "\n".join(lines[end + 1 :])
    return content


def _has_trailing_studio_block(content: str) -> bool:
    """True when the old-place `---` block with a `studio:` root ends the file."""
    lines = content.split("\n")
    end = len(lines) - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    if end < 0 or not _FENCE_RE.match(lines[end].strip()):
        return False
    start = end - 1
    while start >= 0 and not _FENCE_RE.match(lines[start].strip()):
        start -= 1
    if start <= 0:
        return False
    root_key = next((ln.strip() for ln in lines[start + 1 : end] if ln.strip()), "")
    return bool(_STUDIO_ROOT_RE.match(root_key))


def _strip_html_comments(
    content: str, warn: "Callable[[str], None] | None" = None
) -> str:
    """Remove HTML comments (<!-- ... -->) — single-line, inline, or blocks.

    Warns and truncates at the first leftover opener when a comment is left
    unclosed (everything from it to EOF is ignored).
    """
    stripped = _HTML_COMMENT_RE.sub("", content)
    unclosed_at = stripped.find("<!--")
    if unclosed_at != -1:
        if warn is not None:
            warn("Unclosed HTML comment — everything after '<!--' is ignored")
        stripped = stripped[:unclosed_at]
    return stripped


def _check_line(line: str, lineno: int, warn: "Callable[[str], None] | None") -> None:
    """Inspect a line for common image-embed formatting mistakes."""
    if warn is None:
        return

    if _BANG_SPACE_PATTERN.search(line):
        warn(f"Line {lineno}: space between '!' and '[' — use ![alt](URL) not ! [alt](URL)")

    if _PAREN_SPACE_PATTERN.search(line):
        warn(f"Line {lineno}: space before '(' — use ![alt](URL) not ![alt] (URL)")

    if _SWAPPED_PATTERN.search(line):
        warn(f"Line {lineno}: URL and alt text appear swapped. Use ![alt](URL), not ![URL](alt)")

    if _UNCLOSED_PATTERN.search(line):
        warn(f"Line {lineno}: unclosed parenthesis — missing ')' after URL")

    if _LINK_WITHOUT_BANG.search(line):
        warn(f"Line {lineno}: missing '!' prefix — use ![alt](URL) not [alt](URL)")

    if _HTML_IMG_PATTERN.search(line):
        warn(f"Line {lineno}: HTML <img> tag found. Use markdown ![alt](URL) instead")

    if _NON_HTTP_URL.search(line):
        warn(
            f"Line {lineno}: image URL does not start with https:// — "
            "only remote URLs are supported"
        )


def _fence_content(
    lines: list[str], open_index: int, warn: "Callable[[str], None] | None" = None
) -> tuple[list[str], int]:
    """Return the lines inside a ``` fence and the index just past it.

    The opening fence is at open_index; everything up to the closing ``` line
    is content. A fence that is never closed consumes the rest of the file
    (a warning names the unclosed fence).
    """
    inner: list[str] = []
    i = open_index + 1
    while i < len(lines):
        if _FENCE_CLOSE_RE.match(lines[i].strip()):
            return inner, i + 1
        inner.append(lines[i])
        i += 1
    if warn is not None:
        warn(
            f"Line {open_index + 1}: unclosed ``` fence — "
            "treating the rest of the file as its content"
        )
    return inner, len(lines)


def _prompt_from_fence(inner: list[str]) -> str:
    """Join a ```prompt fence's lines, keeping newlines; blank padding dropped."""
    start = 0
    end = len(inner)
    while start < end and not inner[start].strip():
        start += 1
    while end > start and not inner[end - 1].strip():
        end -= 1
    return "\n".join(line.strip() for line in inner[start:end])


def _coerce_duration(raw: str) -> int | str:
    """Return int for numeric tokens, the raw string otherwise (verbatim)."""
    try:
        return int(raw)
    except ValueError:
        return raw


def _route_image(
    alt: str,
    url: str,
    urls: list[str],
    references: dict[str, list[str]],
    declared_slots: list[str] | None,
    primary_slot: str,
) -> None:
    """Route a URL: empty/primary alt → primary; declared alt → named slot.

    Generic media-kind alts ("video", "image", "img", ...) are primary
    markers. `ref`, `reference_images` and `reference_image_urls` all mean the
    declared reference-image slot, first declared wins. Any other alt raises
    ValueError, naming the alt and the declared slots.
    """
    alt = alt.strip()
    if not alt or declared_slots is None or alt == primary_slot or alt in _PRIMARY_ALIASES:
        urls.append(url)
        return
    targets = _SLOT_ALIASES.get(alt)
    if targets is not None:
        slot = next((t for t in targets if t in declared_slots), targets[0])
    else:
        slot = alt
    if slot in declared_slots:
        references.setdefault(slot, []).append(url)
        return
    raise ValueError(
        f"Unknown image alt '{alt}' — this row declares slots {declared_slots}; "
        f"use one of them, ref, or an empty alt for the primary input '{primary_slot}'"
    )


def parse_markdown(
    markdown_content: str,
    warn: "Callable[[str], None] | None" = None,
    declared_slots: list[str] | None = None,
    primary_slot: str = "image",
    allow_empty_prompt: bool = False,
    setting_names: "Collection[str]" = (),
    settings: dict[str, str] | None = None,
) -> tuple[str, list[str], int | None, int | str | None, dict[str, list[str]]]:
    """Parse a .md Markdown file, returning (prompt, urls, frames, duration, references).

    A fence named in setting_names puts its first non-empty line into
    settings (first block of a name wins); without settings none is read.

    A leading whole-line media embed (the previous-generation bookmark) is
    ignored — the prompt is the first non-embed text line, or the content of a
    ```prompt fence. Fenced content is opaque: no media/metadata scanning and
    no format warnings inside a fence.

    Raises:
        ValueError: If no prompt found, if the bullet combines a primary
            image with reference-image URLs (the model cannot combine them),
            if an alt is neither primary nor a declared slot, or if two or
            more primary pictures are given.
    """
    body = _strip_front_matter(markdown_content)
    if _has_trailing_studio_block(body):
        raise ValueError(
            "the studio: block is at the bottom; it now goes at the top of the file, "
            "between two --- lines on line 1"
        )
    lines = _strip_html_comments(body, warn).split("\n")
    prompt = ""
    urls: list[str] = []
    frames: int | None = None
    duration: int | str | None = None
    references: dict[str, list[str]] = {}

    seen_prompt = False
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue

        named = _NAMED_FENCE_RE.match(stripped)
        if settings is not None and named and named.group(1).lower() in setting_names:
            inner, i = _fence_content(lines, i, warn)
            first = next((ln.strip() for ln in inner if ln.strip()), None)
            if first is not None:
                settings.setdefault(named.group(1).lower(), first)
            continue

        if not seen_prompt:
            if _MD_MEDIA_LINE.fullmatch(stripped):
                # A leading media embed (image or video, e.g. the previous
                # generation kept as a bookmark) is ignored — the prompt is
                # the first non-embed text line; references stay below it.
                i += 1
                continue
            if _PROMPT_FENCE_OPEN_RE.match(stripped):
                inner, i = _fence_content(lines, i, warn)
                prompt = _prompt_from_fence(inner)
                seen_prompt = True
                continue
            prompt = stripped
            seen_prompt = True
            i += 1
            continue

        if _DURATION_FENCE_OPEN_RE.match(stripped):
            inner, i = _fence_content(lines, i, warn)
            if duration is None:
                first = next((ln.strip() for ln in inner if ln.strip()), None)
                if first is not None:
                    duration = _coerce_duration(first)
            continue

        match = _IMG_URL_PATTERN.search(line)
        if match:
            _route_image(
                match.group(1), match.group(2), urls, references, declared_slots, primary_slot
            )
        elif _FRAMES_RE.match(stripped):
            if frames is None:
                frames = int(_FRAMES_RE.match(stripped).group(1))
        elif (duration_match := _DURATION_RE.match(stripped)):
            if duration is None:
                duration = _coerce_duration(duration_match.group(1))
        else:
            _check_line(line, i + 1, warn)
        i += 1

    if not prompt and not allow_empty_prompt:
        raise ValueError("No prompt text found in markdown")

    if declared_slots is not None and len(urls) > 1:
        raise ValueError(
            f"{len(urls)} primary pictures found but the primary input "
            f"'{primary_slot}' takes one — keep one or route the rest to a declared slot"
        )

    if urls and any(references.get(name) for name in _REF_SLOT_NAMES):
        raise ValueError(
            "Both a first-frame image (img) and reference-image URLs found — "
            "the model cannot combine them; keep one or the other"
        )

    return prompt, urls, frames, duration, references


def validate_image_urls(urls: list[str], timeout: float = 5.0) -> tuple[list[str], list[str]]:
    """Validate image URLs are reachable via HEAD request.

    Returns:
        Tuple of (valid_urls, invalid_urls). Invalid URLs are stripped.
    """
    valid: list[str] = []
    invalid: list[str] = []
    headers = {"User-Agent": "VideoGenerator/1.0"}
    for url in urls:
        try:
            req = urllib.request.Request(url, method="HEAD", headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status >= 400:
                    invalid.append(url)
                else:
                    valid.append(url)
        except Exception:
            invalid.append(url)
    return valid, invalid


def _card_path(md_path: Path) -> Path:
    return md_path.with_name(f"{md_path.stem}_REJECTED.png")


def _write_rejected_card(md_path: Path, reason: str) -> None:
    """Red 1280x720 card with the reason beside a rejected file; never raises."""
    try:
        width, height = 1280, 720
        image = Image.new("RGB", (width, height), (200, 0, 0))
        draw = ImageDraw.Draw(image)
        font_size = width // 60
        font = ImageFont.load_default(size=font_size)
        margin = width // 100
        y = margin
        for line in textwrap.wrap(reason, (width - 2 * margin) // (font_size // 2)):
            if y + font_size > height - margin:
                break
            draw.text((margin, y), line, fill=(0, 0, 0), font=font)
            y += font_size + font_size // 3
        image.save(_card_path(md_path))
    except Exception as exc:
        logger.error(f"Could not write rejection card for {md_path.name}: {exc}")


def _clear_rejected_card(md_path: Path) -> None:
    try:
        _card_path(md_path).unlink(missing_ok=True)
    except OSError as exc:
        logger.error(f"Could not remove rejection card for {md_path.name}: {exc}")


def read_markdown(
    input_dir: Path,
    dry_run: bool = False,
    declared_slots: list[str] | None = None,
    primary_slot: str = "image",
    allow_empty_prompt: bool = False,
    model: tuple[dict[str, Any], set[str]] | None = None,
) -> list[Markdown]:
    """Read .md Markdown files from input_dir, extract prompt + URLs + frames + duration.

    declared_slots (from the profile's `slots:` key) enables named-slot
    routing; without it every alt falls back to the primary slot.
    primary_slot (from the profile's `image_url_param` key) is the slot name
    that routes to the primary input; unknown alts default there.
    allow_empty_prompt admits files with no prompt text (the profile's prefix
    or suffix then is the whole prompt).
    model (from setting_blocks.model_settings) turns on setting blocks: a file
    whose block the model does not have, or whose value it does not take, is
    rejected; accepted ones land in the file's `settings` overrides.
    Returns [] (with a warning) when the directory holds no .md files.

    FAILS LOUD: a Markdown file that cannot be parsed, or that references media
    URLs the server cannot reach, is REJECTED (logged as an error) — it is
    never silently downgraded to text-to-video or run without its media.
    """
    md_files = sorted(input_dir.rglob("*.md"))
    result: list[Markdown] = []
    rejected = 0
    names = block_names(*model) if model is not None else set()
    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        blocks: dict[str, str] | None = {} if model is not None else None
        try:
            prompt, urls, frames, duration, references = parse_markdown(
                content,
                warn=logger.warning,
                declared_slots=declared_slots,
                primary_slot=primary_slot,
                allow_empty_prompt=allow_empty_prompt,
                setting_names=names,
                settings=blocks,
            )
            settings = check_settings(blocks, model[0]) if blocks and model else {}
        except ValueError as e:
            logger.error(f"Rejected {md_path.name}: {e}")
            _write_rejected_card(md_path, str(e))
            rejected += 1
            continue

        if not dry_run:
            all_urls = list(urls)
            for slot_urls in references.values():
                all_urls.extend(slot_urls)
            if all_urls:
                _, invalid = validate_image_urls(all_urls)
                if invalid:
                    for url in invalid:
                        logger.error(f"Unreachable media URL in {md_path.name}: {url}")
                    reason = (
                        f"{len(invalid)} of {len(all_urls)} "
                        "media URL(s) unreachable — fix the URL or remove the line"
                    )
                    logger.error(f"Rejected {md_path.name}: {reason}")
                    _write_rejected_card(md_path, reason)
                    rejected += 1
                    continue

        _clear_rejected_card(md_path)
        result.append(
            {
                "path": md_path,
                "prompt": prompt,
                "reference_urls": urls,
                "frames": frames,
                "duration": duration,
                "references": references,
                "settings": settings,
            }
        )
    if not result:
        if md_files:
            logger.error(
                f"All {len(md_files)} Markdown file(s) in {input_dir} were rejected"
            )
        else:
            logger.warning(f"No .md files found in {input_dir}")
        return result
    sys.stderr.write(f"Discovered {len(result)} Markdown file(s) in {input_dir}\n")
    return result
