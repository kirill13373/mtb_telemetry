#!/usr/bin/env python3
"""Convert MTB telemetry CSV logs to Sufni Dashboard import format.

Input (default): data/haltech_travel.csv
Expected columns: timestamp, raw, voltage, travel_mm

Output CSV (semicolon-separated): Time;Fork;Shock
- Time: seconds since session start (t=0)
- Fork: normalized fork travel (0..1), defaults to 0.0 when no fork sensor exists
- Shock: normalized shock travel (0..1)

Additionally writes a metadata JSON file containing the UTC session start time
for the Sufni import dialog.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from statistics import median


def _parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _estimate_rate_hz(times_s: list[float]) -> float | None:
    if len(times_s) < 2:
        return None
    deltas = [times_s[i] - times_s[i - 1] for i in range(1, len(times_s))]
    deltas = [dt for dt in deltas if dt > 0]
    if not deltas:
        return None
    dt_med = median(deltas)
    if dt_med <= 0:
        return None
    return 1.0 / dt_med


def convert(
    input_path: Path,
    output_path: Path,
    metadata_path: Path,
    fork_value: float,
    invert_shock_from_mm: bool,
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    records: list[tuple[datetime, float]] = []
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"timestamp", "travel_mm"}
        if reader.fieldnames is None or not required.issubset(set(reader.fieldnames)):
            raise ValueError(
                "Input CSV must contain columns 'timestamp' and 'travel_mm'. "
                f"Found: {reader.fieldnames}"
            )

        for row in reader:
            timestamp = _parse_iso_utc(row["timestamp"])
            travel_mm = float(row["travel_mm"])
            records.append((timestamp, travel_mm))

    if not records:
        raise ValueError("Input CSV contains no data rows.")

    start_utc = records[0][0]
    times_s: list[float] = []
    output_rows: list[dict[str, str]] = []

    for timestamp, travel_mm in records:
        rel_s = (timestamp - start_utc).total_seconds()
        times_s.append(rel_s)

        # haltech_two_point_mm stores 0..100 mm where 0 mm is compressed and
        # 100 mm is extended. Sufni expects Shock 0=extended, 1=compressed.
        shock = travel_mm / 100.0
        if invert_shock_from_mm:
            shock = 1.0 - shock

        output_rows.append(
            {
                "Time": f"{rel_s:.6f}",
                "Fork": f"{_clamp01(fork_value):.6f}",
                "Shock": f"{_clamp01(shock):.6f}",
            }
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Time", "Fork", "Shock"], delimiter=";")
        writer.writeheader()
        writer.writerows(output_rows)

    duration_s = times_s[-1] if times_s else 0.0
    sample_rate_hz = _estimate_rate_hz(times_s)

    metadata = {
        "session_start_utc": start_utc.isoformat().replace("+00:00", "Z"),
        "source_csv": str(input_path),
        "sufni_csv": str(output_path),
        "samples": len(output_rows),
        "duration_s": round(duration_s, 6),
        "estimated_sample_rate_hz": None if sample_rate_hz is None else round(sample_rate_hz, 3),
        "time_source": "RTC-backed system clock (UTC)",
        "notes": "Use session_start_utc as Start time in Sufni import dialog.",
    }

    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")

    print(f"Export written: {output_path}")
    print(f"Metadata written: {metadata_path}")
    print(f"Session start (UTC): {metadata['session_start_utc']}")
    if sample_rate_hz is not None:
        print(f"Estimated sample rate: {sample_rate_hz:.2f} Hz")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert telemetry CSV to Sufni CSV format.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/haltech_travel.csv"),
        help="Input CSV path (default: data/haltech_travel.csv)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/session_sufni.csv"),
        help="Sufni CSV output path (default: data/session_sufni.csv)",
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=Path("data/session_sufni_meta.json"),
        help="Metadata JSON output path (default: data/session_sufni_meta.json)",
    )
    parser.add_argument(
        "--fork-value",
        type=float,
        default=0.0,
        help="Constant normalized fork value (0..1) when no fork sensor is present.",
    )
    parser.add_argument(
        "--no-invert-shock",
        action="store_true",
        help="Disable inversion (use when travel_mm already means 0=extended, 100=compressed).",
    )
    return parser


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    convert(
        input_path=args.input,
        output_path=args.output,
        metadata_path=args.metadata,
        fork_value=args.fork_value,
        invert_shock_from_mm=not args.no_invert_shock,
    )


if __name__ == "__main__":
    main()
