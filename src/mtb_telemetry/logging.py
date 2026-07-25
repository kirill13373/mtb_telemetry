from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


def to_mm(voltage: float, v_zero: float, v_hundred: float) -> float:
    """Map voltage linearly from [v_zero, v_hundred] to [0, 100] mm."""
    span = v_hundred - v_zero
    if abs(span) < 0.01:
        raise ValueError("Calibration span is too small. Check sensor movement and wiring.")

    mm = (voltage - v_zero) * (100.0 / span)
    return max(0.0, min(100.0, mm))


def save_calibration(path: str | Path, v_zero: float, v_hundred: float) -> Path:
    """Persist calibration points to disk as JSON."""
    calibration_path = Path(path)
    calibration_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "v_zero": v_zero,
        "v_hundred": v_hundred,
    }
    calibration_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return calibration_path


def load_calibration(path: str | Path) -> tuple[float, float] | None:
    """Load calibration points if available and valid."""
    calibration_path = Path(path)
    if not calibration_path.exists():
        return None

    payload = json.loads(calibration_path.read_text(encoding="utf-8"))
    return float(payload["v_zero"]), float(payload["v_hundred"])


def append_csv_row(path: str | Path, row: dict[str, Any]) -> Path:
    """Append a single measurement row to a CSV file, creating headers if needed."""
    csv_path = Path(path)
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = list(row.keys())
    file_exists = csv_path.exists() and csv_path.stat().st_size > 0

    with csv_path.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        if not file_exists:
            writer.writeheader()
        writer.writerow(row)

    return csv_path
