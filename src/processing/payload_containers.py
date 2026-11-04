"""ISO-BMFF (MP4) carrier for the generation payload's XMP packet.

The packet is stored in a top-level Adobe XMP ``uuid`` box appended after every
existing box (after ``mdat``). Existing box offsets never move, so the media
index stays valid. All functions are streaming: ``mdat`` payloads are seeked
over, never read.

Note: appending this box changes bytes covered by a provider's C2PA asset hash,
so a fal.ai MP4 will report its manifest as invalid after stamping. That is an
accepted trade-off — the embedded generation recipe is the priority.
"""

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import BinaryIO

MP4_XMP_UUID = bytes.fromhex("BE7ACFCB97A942E89C71999491E3AFAC")
_BOX_HEADER = 8
_BOX_HEADER_64 = 16
_MAX_XMP_BYTES = 16 * 1024 * 1024

_ESCAPES = {"&": "&amp;", "<": "&lt;", ">": "&gt;"}
_UNESCAPES = {escaped: ch for ch, escaped in _ESCAPES.items()}
_DESCRIPTION_OPEN = b"<dc:description>"
_DESCRIPTION_CLOSE = b"</dc:description>"
_DESCRIPTION_NS = b'xmlns:dc="http://purl.org/dc/elements/1.1/"'
_RDF_DESCRIPTION = b"<rdf:Description"


def _merge_packet(existing: bytes, escaped: str) -> bytes | None:
    """Return ``existing`` with only its dc:description content replaced.

    The rdf:Description attributes and every sibling element are preserved
    byte-for-byte. Returns None when the packet has no rdf:Description to
    merge into.
    """
    content = escaped.encode()
    start = existing.find(_DESCRIPTION_OPEN)
    end = (
        existing.find(_DESCRIPTION_CLOSE, start + len(_DESCRIPTION_OPEN))
        if start >= 0
        else -1
    )
    if start >= 0 and end >= 0:
        head = existing[: start + len(_DESCRIPTION_OPEN)]
        return head + content + existing[end:]
    return _insert_description(existing, content)


def _insert_description(existing: bytes, content: bytes) -> bytes | None:
    """Insert a dc:description as the first child of an existing rdf:Description."""
    pos = existing.find(_RDF_DESCRIPTION)
    if pos < 0:
        return None
    end_tag = existing.find(b">", pos)
    if end_tag < 0:
        return None
    xml = existing
    if _DESCRIPTION_NS not in xml[pos:end_tag]:
        marker = len(_RDF_DESCRIPTION)
        xml = xml[: pos + marker] + b" " + _DESCRIPTION_NS + xml[pos + marker :]
        end_tag = xml.find(b">", pos)
    description = _DESCRIPTION_OPEN + content + _DESCRIPTION_CLOSE
    return xml[: end_tag + 1] + description + xml[end_tag + 1 :]


def xmp_packet(text: str, existing: bytes | None = None) -> bytes:
    """Serialize text as an XMP packet with the text in dc:description.

    When ``existing`` is given its packet bytes are preserved and only the
    dc:description content is replaced. A fresh packet is built when there is
    nothing to merge into.
    """
    escaped = "".join(_ESCAPES.get(ch, ch) for ch in text)
    if existing:
        merged = _merge_packet(existing, escaped)
        if merged is not None:
            return merged
    return (
        '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        '<rdf:Description rdf:about="" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:description>{escaped}</dc:description>"
        "</rdf:Description></rdf:RDF></x:xmpmeta>"
    ).encode()


def extract_description(xml: bytes) -> str:
    """Pull the dc:description text back out of a packet and unescape it."""
    start = xml.find(_DESCRIPTION_OPEN)
    end = xml.find(_DESCRIPTION_CLOSE, start)
    if start < 0 or end < 0:
        return ""
    text = xml[start + len(_DESCRIPTION_OPEN) : end].decode("utf-8", errors="replace")
    for escaped, ch in _UNESCAPES.items():
        text = text.replace(escaped, ch)
    return text


# ── ISO-BMFF boxes ───────────────────────────────────────────────────────────


def _is_printable_fourcc(box_type: bytes) -> bool:
    return len(box_type) == 4 and all(0x20 <= byte < 0x7F for byte in box_type)


def iter_top_level_boxes(fh: BinaryIO) -> Iterator[tuple[int, int, bytes]]:
    """Yield ``(offset, size, type)`` for every top-level ISO-BMFF box.

    Handles 32-bit sizes, 64-bit ``largesize`` (``size == 1``) and open-ended
    boxes (``size == 0``, normalised to the rest of the file). Box payloads are
    seeked over, so a multi-gigabyte ``mdat`` is never read. Raises ValueError
    when the file is not a readable ISO-BMFF container.
    """
    fh.seek(0, 2)
    file_size = fh.tell()
    if file_size < _BOX_HEADER:
        raise ValueError("not an MP4 file: fewer than 8 bytes")

    offset = 0
    first = True
    while offset + _BOX_HEADER <= file_size:
        fh.seek(offset)
        header = fh.read(_BOX_HEADER)
        if len(header) < _BOX_HEADER:
            break
        size = struct.unpack(">I", header[:4])[0]
        box_type = header[4:8]
        header_size = _BOX_HEADER

        if size == 1:
            largesize = fh.read(8)
            if len(largesize) < 8:
                raise ValueError(f"truncated 64-bit box header at offset {offset}")
            size = struct.unpack(">Q", largesize)[0]
            header_size = _BOX_HEADER_64
        elif size == 0:
            size = file_size - offset

        if size < header_size:
            raise ValueError(f"invalid box size {size} at offset {offset}")
        if offset + size > file_size:
            label = box_type.decode("ascii", errors="replace")
            raise ValueError(
                f"box '{label}' at offset {offset} runs past end of file"
            )
        if first and not _is_printable_fourcc(box_type):
            raise ValueError(
                f"not an MP4 file: first box type {box_type!r} is not a fourcc"
            )
        first = False

        yield offset, size, box_type
        offset += size


def _declared_size(fh: BinaryIO, offset: int) -> int:
    fh.seek(offset)
    raw = fh.read(4)
    if len(raw) < 4:
        raise ValueError(f"truncated box header at offset {offset}")
    return struct.unpack(">I", raw)[0]


def _box_header_size(fh: BinaryIO, offset: int) -> int:
    return _BOX_HEADER_64 if _declared_size(fh, offset) == 1 else _BOX_HEADER


def _is_adobe_xmp_box(fh: BinaryIO, offset: int, size: int) -> bool:
    header_size = _box_header_size(fh, offset)
    if size < header_size + len(MP4_XMP_UUID):
        return False
    fh.seek(offset + header_size)
    return fh.read(len(MP4_XMP_UUID)) == MP4_XMP_UUID


def _iter_xmp_payloads(fh: BinaryIO) -> Iterator[bytes]:
    for offset, size, box_type in iter_top_level_boxes(fh):
        if box_type != b"uuid":
            continue
        header_size = _box_header_size(fh, offset)
        payload_size = size - header_size - len(MP4_XMP_UUID)
        if payload_size <= 0 or payload_size > _MAX_XMP_BYTES:
            continue
        fh.seek(offset + header_size)
        if fh.read(len(MP4_XMP_UUID)) != MP4_XMP_UUID:
            continue
        yield fh.read(payload_size)


def make_xmp_box(packet: bytes) -> bytes:
    """Wrap an XMP packet in a top-level Adobe ``uuid`` box."""
    size = _BOX_HEADER + len(MP4_XMP_UUID) + len(packet)
    if size > 0xFFFFFFFF:
        raise ValueError(f"XMP packet too large for a 32-bit box: {size} bytes")
    return struct.pack(">I", size) + b"uuid" + MP4_XMP_UUID + packet


def append_xmp(path: Path, packet: bytes) -> None:
    """Append an XMP packet as the last top-level box.

    A trailing Adobe-XMP box is truncated first so re-stamping is idempotent.
    Only a trailing box is ever removed: truncating a box before ``mdat`` would
    shift the media's chunk offsets and corrupt playback.
    """
    if not packet:
        raise ValueError("empty XMP packet")
    with path.open("r+b") as fh:
        last: tuple[int, int, bytes] | None = None
        for last in iter_top_level_boxes(fh):
            pass
        if last is None:
            raise ValueError("not an MP4 file: no top-level boxes")
        offset, size, box_type = last
        if _declared_size(fh, offset) == 0:
            raise ValueError(
                "cannot append after an open-ended top-level box "
                f"(offset {offset}); the file's mdat has no explicit size"
            )
        if box_type == b"uuid" and _is_adobe_xmp_box(fh, offset, size):
            fh.truncate(offset)
        fh.seek(0, 2)
        fh.write(make_xmp_box(packet))
        fh.flush()


def read_xmp(path: Path) -> str | None:
    """Return the last Adobe-XMP packet's dc:description text, or None."""
    last: str | None = None
    with path.open("rb") as fh:
        for payload in _iter_xmp_payloads(fh):
            text = extract_description(payload)
            if text:
                last = text
    return last


def has_xmp(path: Path) -> bool:
    """Return True when the file carries a top-level Adobe-XMP ``uuid`` box."""
    try:
        with path.open("rb") as fh:
            for _ in _iter_xmp_payloads(fh):
                return True
    except (OSError, ValueError):
        return False
    return False
