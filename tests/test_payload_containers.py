"""Tests for the MP4 XMP carrier (pure stdlib, no exiftool needed)."""

import struct
from pathlib import Path

import pytest

from src.processing.payload_containers import (
    MP4_XMP_UUID,
    append_xmp,
    extract_description,
    has_xmp,
    iter_top_level_boxes,
    make_xmp_box,
    read_xmp,
    xmp_packet,
)


def _box(box_type: bytes, payload: bytes = b"") -> bytes:
    return struct.pack(">I", 8 + len(payload)) + box_type + payload


def _large_box(box_type: bytes, payload: bytes = b"") -> bytes:
    return (
        struct.pack(">I", 1)
        + box_type
        + struct.pack(">Q", 16 + len(payload))
        + payload
    )


def _mp4(*extra: bytes) -> bytes:
    return (
        _box(b"ftyp", b"isom")
        + _box(b"moov", b"\x00" * 8)
        + _box(b"mdat", b"\x01\x02\x03")
        + b"".join(extra)
    )


def _write(tmp_path: Path, data: bytes, name: str = "clip.mp4") -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_packet_escapes_and_round_trips() -> None:
    text = 'prompt with & <tags> and "quotes"'
    packet = xmp_packet(text)

    assert b"&amp;" in packet
    assert b"&lt;" in packet
    assert b"&gt;" in packet
    assert extract_description(packet) == text


def test_extract_description_returns_empty_without_a_description() -> None:
    assert extract_description(b"<x:xmpmeta/>") == ""


def test_make_xmp_box_layout() -> None:
    packet = b"<packet/>"
    box = make_xmp_box(packet)

    assert struct.unpack(">I", box[:4])[0] == 8 + 16 + len(packet)
    assert box[4:8] == b"uuid"
    assert box[8:24] == MP4_XMP_UUID
    assert box[24:] == packet


def test_append_leaves_existing_bytes_untouched(tmp_path: Path) -> None:
    path = _write(tmp_path, _mp4())
    before = path.read_bytes()

    append_xmp(path, xmp_packet('{"schema": 1}'))

    after = path.read_bytes()
    assert after[: len(before)] == before
    assert len(after) == len(before) + 8 + 16 + len(xmp_packet('{"schema": 1}'))
    assert read_xmp(path) == '{"schema": 1}'


def test_append_is_idempotent(tmp_path: Path) -> None:
    path = _write(tmp_path, _mp4())
    before = path.read_bytes()

    append_xmp(path, xmp_packet("first"))
    first_pass = path.read_bytes()
    append_xmp(path, xmp_packet("other"))
    second_pass = path.read_bytes()

    assert len(second_pass) == len(first_pass)
    assert second_pass[: len(before)] == before
    assert read_xmp(path) == "other"
    with path.open("rb") as fh:
        assert sum(1 for _, _, t in iter_top_level_boxes(fh) if t == b"uuid") == 1


def test_appends_after_moov_at_the_end(tmp_path: Path) -> None:
    path = _write(
        tmp_path, _box(b"ftyp", b"isom") + _box(b"mdat", b"data") + _box(b"moov")
    )

    append_xmp(path, xmp_packet("recipe"))

    with path.open("rb") as fh:
        boxes = [(t, size) for _, size, t in iter_top_level_boxes(fh)]
    assert boxes[-1] == (b"uuid", 8 + 16 + len(xmp_packet("recipe")))
    assert read_xmp(path) == "recipe"


def test_appends_after_trailing_free_box(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _box(b"ftyp", b"isom") + _box(b"mdat", b"data") + _box(b"free") + _box(b"moov"),
    )

    append_xmp(path, xmp_packet("recipe"))

    assert read_xmp(path) == "recipe"


def test_iterator_handles_64_bit_largesize(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _box(b"ftyp", b"isom") + _large_box(b"moov", b"x" * 20) + _box(b"mdat"),
    )

    with path.open("rb") as fh:
        boxes = list(iter_top_level_boxes(fh))
    assert [(t, size) for _, size, t in boxes] == [
        (b"ftyp", 12),
        (b"moov", 36),
        (b"mdat", 8),
    ]

    append_xmp(path, xmp_packet("recipe"))
    assert read_xmp(path) == "recipe"


def test_reader_returns_the_last_of_multiple_xmp_boxes(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        _mp4(make_xmp_box(xmp_packet("first")), make_xmp_box(xmp_packet("second"))),
    )

    assert read_xmp(path) == "second"


def test_non_mp4_input_raises_a_clear_error(tmp_path: Path) -> None:
    path = _write(tmp_path, b"not an mp4 file", name="not.mp4")

    with pytest.raises(ValueError, match="MP4|box"):
        append_xmp(path, xmp_packet("recipe"))
    with pytest.raises(ValueError, match="MP4|box"):
        read_xmp(path)
    assert has_xmp(path) is False


def test_truncated_file_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, _mp4()[:-1])

    with pytest.raises(ValueError, match="past end of file"):
        read_xmp(path)


def test_open_ended_trailing_box_is_refused(tmp_path: Path) -> None:
    path = _write(tmp_path, struct.pack(">I", 0) + b"mdat" + b"payload")

    with pytest.raises(ValueError, match="open-ended"):
        append_xmp(path, xmp_packet("recipe"))


def test_has_xmp(tmp_path: Path) -> None:
    path = _write(tmp_path, _mp4())
    assert has_xmp(path) is False

    append_xmp(path, xmp_packet("{}"))
    assert has_xmp(path) is True
