from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import multiprocessing
from pathlib import Path

import pytest

from mtb_telemetry.binary_logging import (
    BinaryLogHeader,
    BinarySessionWriter,
    FORMAT_VERSION,
    RECORD_STRUCT,
    read_binary_log,
)
from scripts.export_sufni_csv import convert


def build_header(block_records: int = 2) -> BinaryLogHeader:
    return BinaryLogHeader.from_session(
        session_start_utc=datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc),
        target_hz=500.0,
        block_records=block_records,
        shock_v_zero=0.0,
        shock_v_full=5.0,
        fork_v_zero=0.0,
        fork_v_full=5.0,
        shock_travel_mm_max=100.0,
        fork_travel_mm_max=200.0,
    )


def test_header_roundtrip_preserves_session_metadata() -> None:
    header = build_header()

    decoded = BinaryLogHeader.unpack(header.pack())

    assert decoded == header
    assert decoded.session_start_utc == datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def test_header_rejects_unknown_version() -> None:
    packed = bytearray(build_header().pack())
    packed[len(b"MTBTLOG\0"):len(b"MTBTLOG\0") + 2] = (FORMAT_VERSION + 1).to_bytes(2, "little")

    with pytest.raises(ValueError, match="Unsupported binary log version"):
        BinaryLogHeader.unpack(bytes(packed))


def test_reader_ignores_trailing_partial_record(tmp_path: Path) -> None:
    path = tmp_path / "truncated.mtblog"
    path.write_bytes(
        build_header().pack()
        + RECORD_STRUCT.pack(0, 123, 456)
        + RECORD_STRUCT.pack(2_000_000, 789, 1011)[:5]
    )

    header, records = read_binary_log(path)

    assert header.target_hz == 500.0
    assert [(record.offset_ns, record.shock_raw, record.fork_raw) for record in records] == [
        (0, 123, 456)
    ]


def test_spawned_writer_drains_full_and_partial_blocks(tmp_path: Path) -> None:
    path = tmp_path / "session.mtblog"
    writer = BinarySessionWriter(
        path,
        build_header(block_records=2),
        queue_blocks=2,
        fsync_interval_s=0,
        context=multiprocessing.get_context("spawn"),
    )
    writer.append(0, 10, 20)
    writer.append(2_000_000, 30, 40)
    writer.append(4_000_000, 50, 60)

    metrics = writer.close()
    _, records = read_binary_log(path)

    assert metrics["ok"] is True
    assert metrics["records_enqueued"] == 3
    assert metrics["blocks_written"] == 2
    assert [(record.shock_raw, record.fork_raw) for record in records] == [
        (10, 20),
        (30, 40),
        (50, 60),
    ]


def test_binary_log_exports_to_sufni_with_embedded_session_start(tmp_path: Path) -> None:
    input_path = tmp_path / "session.mtblog"
    output_path = tmp_path / "session_sufni.csv"
    metadata_path = tmp_path / "session_sufni_meta.json"
    full_scale = (1 << 23) - 1
    input_path.write_bytes(
        build_header().pack()
        + RECORD_STRUCT.pack(0, 0, 0)
        + RECORD_STRUCT.pack(2_000_000, full_scale, full_scale)
    )

    convert(
        input_path=input_path,
        output_path=output_path,
        metadata_path=metadata_path,
        fork_value=0.0,
        fork_travel_mm_max=1.0,
        shock_travel_mm_max=1.0,
        invert_shock_from_mm=True,
    )

    with output_path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle, delimiter=";"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

    assert rows == [
        {"Time": "0.000000", "Fork": "1.000000", "Shock": "1.000000"},
        {"Time": "0.002000", "Fork": "0.000000", "Shock": "0.000000"},
    ]
    assert metadata["session_start_utc"] == "2026-08-05T12:00:00Z"
    assert metadata["source_format"] == "mtblog-v1"
