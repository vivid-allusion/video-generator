"""Shared type definitions for the application."""

from pathlib import Path
from typing import Any, NotRequired, TypedDict


class Markdown(TypedDict):
    """A parsed .md Markdown file with its extracted data."""

    path: Path
    prompt: str
    reference_urls: list[str]
    frames: int | None
    duration: int | str | None
    references: dict[str, list[str]]
    settings: NotRequired[dict[str, Any]]
