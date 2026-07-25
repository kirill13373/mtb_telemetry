from __future__ import annotations

from pathlib import Path

from mtb_telemetry.logging import append_csv_row, load_calibration, save_calibration, to_mm


def test_to_mm_scales_and_clamps_linearly() -> None:
    assert to_mm(2.0, 1.0, 3.0) == 50.0
    assert to_mm(0.0, 1.0, 3.0) == 0.0
    assert to_mm(4.0, 1.0, 3.0) == 100.0


def test_save_and_load_calibration(tmp_path: Path) -> None:
    calibration_path = tmp_path / "calibration.json"

    save_calibration(calibration_path, 1.23, 4.56)

    assert load_calibration(calibration_path) == (1.23, 4.56)


def test_append_csv_row_writes_header_and_values(tmp_path: Path) -> None:
    log_path = tmp_path / "travel.csv"

    append_csv_row(
        log_path,
        {
            "timestamp": "2026-07-25T10:00:00",
            "raw": 1234,
            "voltage": 2.5,
            "travel_mm": 35.2,
        },
    )

    contents = log_path.read_text(encoding="utf-8")
    assert "timestamp,raw,voltage,travel_mm" in contents
    assert "2026-07-25T10:00:00,1234,2.5,35.2" in contents
