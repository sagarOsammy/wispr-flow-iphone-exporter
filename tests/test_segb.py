from __future__ import annotations

import struct
import zlib
from pathlib import Path

from wispr_flow_iphone_exporter.segb import SegbState, decode_segb


def _segb(path: Path, payload: bytes) -> None:
    entry = struct.pack("<Ii", zlib.crc32(payload) & 0xFFFFFFFF, 0) + payload
    padded_length = (len(entry) + 3) // 4 * 4
    data = entry + b"\0" * (padded_length - len(entry))
    header = bytearray(32)
    header[:4] = b"SEGB"
    struct.pack_into("<I", header, 4, 1)
    struct.pack_into("<d", header, 8, 0.0)
    trailer = struct.pack("<IId", len(entry), SegbState.WRITTEN, 1.0)
    path.write_bytes(bytes(header) + data + trailer)


def test_decode_segb_reads_payload_and_crc(tmp_path: Path) -> None:
    path = tmp_path / "record.segb"
    _segb(path, b"hello")

    header_time, entries = decode_segb(path)

    assert header_time.year == 2001
    assert len(entries) == 1
    assert entries[0].state_name == "written"
    assert entries[0].payload == b"hello"
    assert entries[0].crc_passed is True
