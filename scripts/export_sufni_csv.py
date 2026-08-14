#!/usr/bin/env python3
"""Convert MTB telemetry binary or CSV logs to Sufni Dashboard import format.

Input (default): data/haltech_travel.csv
Expected columns (legacy): timestamp, raw, voltage, travel_mm
Expected columns (dual sensor):
    timestamp, shock_raw, shock_voltage, shock_travel_mm,
    fork_raw, fork_voltage, fork_travel_mm

Timestamp column format (both are accepted):
  - ISO-8601 UTC string (legacy):   2026-07-31T09:15:13.123456+00:00
  - Monotonic offset in seconds (new):  0.000000  / 1.234567
    When using monotonic offsets, pass --session-start-utc with the
    run_started_utc value from last_run_metrics.json to produce correct
    absolute UTC times in the output metadata.

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

from mtb_telemetry.binary_logging import MAGIC, read_binary_log


def _clamp01(value: float) -> float:
    """Clamp a numeric value to the inclusive range [0.0, 1.0]."""
    if value < 0.0:
        return 0.0
    if value > 1.0:
        return 1.0
    return value


def _parse_iso_utc(value: str) -> datetime:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _is_monotonic_offset(value: str) -> bool:
    """Return True when the timestamp column holds a plain decimal offset (seconds)."""
    try:
        float(value.strip())
        return True
    except ValueError:
        return False


def _parse_timestamp(value: str, session_start_utc: datetime | None) -> tuple[float, datetime | None]:
    """Return (relative_seconds, utc_datetime_or_None) from a timestamp cell.

    Supports both ISO-8601 UTC strings and plain monotonic-offset floats.
    For monotonic offsets, utc_datetime is reconstructed from session_start_utc
    when available; otherwise None is returned for the utc field.
    """
    if _is_monotonic_offset(value):
        offset_s = float(value.strip())
        if session_start_utc is not None:
            from datetime import timedelta
            utc_dt = session_start_utc + timedelta(seconds=offset_s)
        else:
            utc_dt = None
        return offset_s, utc_dt
    else:
        utc_dt = _parse_iso_utc(value)
        return None, utc_dt  # relative time will be computed later


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


def _raw_to_voltage(raw_value: int, vref: float = 5.0, pga: int = 1) -> float:
    """Convert a signed ADS1256 code without importing the hardware driver."""
    return (raw_value / ((1 << 23) - 1)) * (vref / pga)


def _to_mm(voltage: float, v_zero: float, v_full: float, full_scale_mm: float) -> float:
    span = v_full - v_zero
    if abs(span) < 0.01:
        raise ValueError("Calibration span in binary log is too small")
    return max(0.0, min(full_scale_mm, (voltage - v_zero) * (full_scale_mm / span)))


def _is_binary_log(path: Path) -> bool:
    with path.open("rb") as handle:
        return handle.read(len(MAGIC)) == MAGIC


def convert(
    input_path: Path,
    output_path: Path,
    metadata_path: Path,
    fork_value: float,
    fork_travel_mm_max: float,
    shock_travel_mm_max: float,
    invert_shock_from_mm: bool,
    session_start_utc: datetime | None = None,
) -> None:
    if not input_path.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")

    records: list[tuple[float | None, datetime | None, float, float | None]] = []
    binary_input = _is_binary_log(input_path)
    shock_sensor_travel_mm_max = shock_travel_mm_max
    fork_sensor_travel_mm_max = fork_travel_mm_max
    if binary_input:
        header, binary_records = read_binary_log(input_path)
        session_start_utc = header.session_start_utc
        shock_sensor_travel_mm_max = header.shock_travel_mm_max
        fork_sensor_travel_mm_max = header.fork_travel_mm_max
        for record in binary_records:
            shock_travel_mm = _to_mm(
                _raw_to_voltage(record.shock_raw),
                header.shock_v_zero,
                header.shock_v_full,
                shock_sensor_travel_mm_max,
            )
            fork_travel_mm = _to_mm(
                _raw_to_voltage(record.fork_raw),
                header.fork_v_zero,
                header.fork_v_full,
                fork_sensor_travel_mm_max,
            )
            records.append((record.offset_ns / 1_000_000_000, None, shock_travel_mm, fork_travel_mm))
    else:
        with input_path.open("r", encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fieldnames = set(reader.fieldnames or [])
            has_legacy_shock = "travel_mm" in fieldnames
            has_dual_shock = "shock_travel_mm" in fieldnames
            if reader.fieldnames is None or "timestamp" not in fieldnames or (not has_legacy_shock and not has_dual_shock):
                raise ValueError(
                    "Input CSV must contain 'timestamp' plus 'travel_mm' (legacy) "
                    "or 'shock_travel_mm' (dual sensor). "
                    f"Found: {reader.fieldnames}"
                )

            for row in reader:
                offset_s, utc_dt = _parse_timestamp(row["timestamp"], session_start_utc)
                shock_travel_mm = float(
                    row["shock_travel_mm"] if has_dual_shock else row["travel_mm"]
                )
                fork_travel_mm: float | None = None
                if "fork_travel_mm" in fieldnames and row.get("fork_travel_mm") not in {None, ""}:
                    fork_travel_mm = float(row["fork_travel_mm"])

                records.append((offset_s, utc_dt, shock_travel_mm, fork_travel_mm))

    if not records:
        raise ValueError("Input log contains no data records.")

    # Determine time source and session start UTC
    first_offset, first_utc, _, _ = records[0]
    uses_monotonic = first_offset is not None
    if uses_monotonic:
        time_source = (
            "monotonic nanosecond offset (binary session header)"
            if binary_input
            else "monotonic offset (reconstructed from session_start_utc)"
        )
        resolved_start_utc = session_start_utc
    else:
        # Legacy ISO-UTC timestamps
        time_source = "RTC-backed system clock (UTC)"
        resolved_start_utc = first_utc

    times_s: list[float] = []
    output_rows: list[dict[str, str]] = []

    for offset_s, utc_dt, shock_travel_mm, fork_travel_mm in records:
        if uses_monotonic:
            rel_s = offset_s  # type: ignore[arg-type]
        else:
            assert utc_dt is not None and resolved_start_utc is not None
            rel_s = (utc_dt - resolved_start_utc).total_seconds()
        times_s.append(rel_s)

        # haltech_two_point_mm stores 0..100 mm where 0 mm is compressed and
        # 100 mm is extended. Sufni expects Shock 0=extended, 1=compressed.
        if binary_input:
            shock = (shock_sensor_travel_mm_max - shock_travel_mm) / shock_travel_mm_max
        else:
            shock = shock_travel_mm / shock_travel_mm_max
            if invert_shock_from_mm:
                shock = 1.0 - shock

        if fork_travel_mm is None:
            fork = _clamp01(fork_value)
        else:
            if binary_input:
                fork = (fork_sensor_travel_mm_max - fork_travel_mm) / fork_travel_mm_max
            else:
                # Same convention as shock in logger CSV: 0 mm compressed, max mm extended.
                fork = 1.0 - (fork_travel_mm / fork_travel_mm_max)

        output_rows.append(
            {
                "Time": f"{rel_s:.6f}",
                "Fork": f"{_clamp01(fork):.6f}",
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
        "session_start_utc": None
        if resolved_start_utc is None
        else resolved_start_utc.isoformat().replace("+00:00", "Z"),
        "source_log": str(input_path),
        "source_format": "mtblog-v1" if binary_input else "csv",
        "source_csv": None if binary_input else str(input_path),
        "sufni_csv": str(output_path),
        "samples": len(output_rows),
        "duration_s": round(duration_s, 6),
        "estimated_sample_rate_hz": None if sample_rate_hz is None else round(sample_rate_hz, 3),
        "time_source": time_source,
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
    parser = argparse.ArgumentParser(description="Convert a telemetry binary/CSV log to Sufni CSV.")
    parser.add_argument(
        "--input",
        type=Path,
        default=Path("data/haltech_travel.csv"),
        help="Input .mtblog or CSV path (default: data/haltech_travel.csv)",
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
        "--session-start-utc",
        type=str,
        default=None,
        help=(
            "Session start time in ISO-8601 UTC format. Required only when a legacy CSV "
            "uses monotonic offsets. Binary logs contain their own UTC session start."
        ),
    )
    parser.add_argument(
        "--fork-value",
        type=float,
        default=0.0,
        help="Constant normalized fork value (0..1) when no fork sensor is present.",
    )
    parser.add_argument(
        "--shock-travel-mm-max",
        type=float,
        default=100.0,
        help="Shock full-travel reference in mm for normalization (default: 100).",
    )
    parser.add_argument(
        "--fork-travel-mm-max",
        type=float,
        default=200.0,
        help="Fork full-travel reference in mm for normalization (default: 200).",
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
    session_start_utc: datetime | None = None
    if args.session_start_utc is not None:
        session_start_utc = _parse_iso_utc(args.session_start_utc)
    if args.shock_travel_mm_max <= 0:
        parser.error("--shock-travel-mm-max must be > 0")
    if args.fork_travel_mm_max <= 0:
        parser.error("--fork-travel-mm-max must be > 0")
    convert(
        input_path=args.input,
        output_path=args.output,
        metadata_path=args.metadata,
        fork_value=args.fork_value,
        fork_travel_mm_max=args.fork_travel_mm_max,
        shock_travel_mm_max=args.shock_travel_mm_max,
        invert_shock_from_mm=not args.no_invert_shock,
        session_start_utc=session_start_utc,
    )


if __name__ == "__main__":
    main()
