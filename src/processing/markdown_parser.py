"""Markdown-file parsing for video generation.

Parses Markdown `.md` files and extracts:
- Text prompt from the first non-empty line that is not a whole-line media
  embed
- Reference URLs from markdown ![alt](URL) syntax — empty alt, the primary
  slot name, or an unknown alt feeds the primary slot; a declared named alt
  feeds the named slot
- Optional frame count from a `frames: N` line (deprecated, converted via fps)
- Optional raw duration from a `duration: <int|token>` line (verbatim)

HTML comments are ignored: anything between <!-- and --> (single-line,
inline, or spanning multiple lines) is stripped before parsing, so
commented-out prompts, images, or metadata never reach the payload.

A trailing `---`-fenced YAML block whose root key is `studio:` is the IDE's
cull-marks metadata. It is skipped whole — never a prompt, never a URL, never a
warning — before any line is inspected. Detection is structural (fence + root
key), so malformed YAML inside the block is skipped rather than raising.

A leading whole-line media embed — image or video, any target — is the
previous generation kept by tooling as a visual bookmark: it is skipped whole
(never the prompt, never a reference). References stay below the prompt.

Format:
    Line 1: Text prompt
    Lines 2+: ![alt](URL), frames: N and/or duration: <value>
    (optional) trailing `studio:` marks block
"""

import re
import sys
import urllib.request
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from ..datatypes import Markdown

if TYPE_CHECKING:
    from collections.abc import Callable

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

_PRIMARY_ALIASES = {"video", "image", "source", "media", "src", "input"}


def _strip_trailing_studio_block(content: str) -> str:
    """Drop a trailing `---`-fenced block whose root key is `studio:`.

    The IDE appends cull marks as a namespaced trailing block, e.g.::

        ---
        studio:
          marks:
            rating: 3
            colors: [green, red]
            emoji: ["😀"]
        ---

    The block is metadata, never a prompt or a URL, so it is removed whole
    (no warnings). Detection is structural — a closing fence on the last
    non-blank line, a matching opening fence, and a `studio:` root key as the
    first non-blank line inside — so malformed YAML is skipped, never parsed.
    A trailing fence with any other root key, or content after the fence, is
    left untouched (today's behaviour).
    """
    lines = content.split("\n")

    end = len(lines) - 1
    while end >= 0 and not lines[end].strip():
        end -= 1
    if end < 0 or not _FENCE_RE.match(lines[end].strip()):
        return content

    start = end - 1
    while start >= 0 and not _FENCE_RE.match(lines[start].strip()):
        start -= 1
    if start < 0:
        return content

    root_key = ""
    for line in lines[start + 1 : end]:
        if line.strip():
            root_key = line.strip()
            break
    if not _STUDIO_ROOT_RE.match(root_key):
        return content

    return "\n".join(lines[:start])


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
    warn: "Callable[[str], None] | None" = None,
) -> None:
    """Route a URL: empty/primary/unknown alt → primary; declared alt → named slot.

    Unknown alts default to the primary slot (with a warning) instead of
    erroring the Markdown file. Generic media-kind alts ("video", "image", "source",
    ...) are treated as primary markers and never warn.
    """
    alt = alt.strip()
    if not alt or declared_slots is None or alt == primary_slot or alt in _PRIMARY_ALIASES:
        urls.append(url)
        return
    if alt in declared_slots:
        references.setdefault(alt, []).append(url)
        return
    if warn is not None:
        warn(
            f"Unknown reference slot '{alt}' — defaulting to primary slot "
            f"'{primary_slot}'"
        )
    urls.append(url)


def parse_markdown(
    markdown_content: str,
    warn: "Callable[[str], None] | None" = None,
    declared_slots: list[str] | None = None,
    primary_slot: str = "image",
) -> tuple[str, list[str], int | None, int | str | None, dict[str, list[str]]]:
    """Parse a .md Markdown file, returning (prompt, urls, frames, duration, references).

    A leading whole-line media embed (the previous-generation bookmark) is
    ignored — the prompt is the first non-embed text line.

    Raises:
        ValueError: If no prompt found.
    """
    lines = _strip_html_comments(
        _strip_trailing_studio_block(markdown_content), warn
    ).split("\n")
    prompt = ""
    urls: list[str] = []
    frames: int | None = None
    duration: int | str | None = None
    references: dict[str, list[str]] = {}

    seen_prompt = False
    for lineno, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue

        if not seen_prompt:
            if _MD_MEDIA_LINE.fullmatch(stripped):
                # A leading media embed (image or video, e.g. the previous
                # generation kept as a bookmark) is ignored — the prompt is
                # the first non-embed text line; references stay below it.
                continue
            prompt = stripped
            seen_prompt = True
            continue

        match = _IMG_URL_PATTERN.search(line)
        if match:
            _route_image(
                match.group(1), match.group(2), urls, references, declared_slots, primary_slot, warn
            )
        elif _FRAMES_RE.match(stripped):
            if frames is None:
                frames = int(_FRAMES_RE.match(stripped).group(1))
        elif (duration_match := _DURATION_RE.match(stripped)):
            if duration is None:
                duration = _coerce_duration(duration_match.group(1))
        else:
            _check_line(line, lineno, warn)

    if not prompt:
        raise ValueError("No prompt text found in markdown")

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


def read_markdown(
    input_dir: Path,
    dry_run: bool = False,
    declared_slots: list[str] | None = None,
    primary_slot: str = "image",
) -> list[Markdown]:
    """Read .md Markdown files from input_dir, extract prompt + URLs + frames + duration.

    declared_slots (from the profile's `slots:` key) enables named-slot
    routing; without it every alt falls back to the primary slot.
    primary_slot (from the profile's `image_url_param` key) is the slot name
    that routes to the primary input; unknown alts default there.
    Returns [] (with a warning) when the directory holds no .md files.

    FAILS LOUD: a Markdown file that cannot be parsed, or that references media
    URLs the server cannot reach, is REJECTED (logged as an error) — it is
    never silently downgraded to text-to-video or run without its media.
    """
    md_files = sorted(input_dir.rglob("*.md"))
    result: list[Markdown] = []
    rejected = 0
    for md_path in md_files:
        content = md_path.read_text(encoding="utf-8")
        try:
            prompt, urls, frames, duration, references = parse_markdown(
                content,
                warn=logger.warning,
                declared_slots=declared_slots,
                primary_slot=primary_slot,
            )
        except ValueError as e:
            logger.error(f"Rejected {md_path.name}: {e}")
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
                    logger.error(
                        f"Rejected {md_path.name}: {len(invalid)} of {len(all_urls)} "
                        "media URL(s) unreachable — fix the URL or remove the line"
                    )
                    rejected += 1
                    continue

        result.append(
            {
                "path": md_path,
                "prompt": prompt,
                "reference_urls": urls,
                "frames": frames,
                "duration": duration,
                "references": references,
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
