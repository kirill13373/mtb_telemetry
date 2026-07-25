"""Two-point calibration and live mm output for Haltech travel sensor.

Workflow:
1. Place suspension at 0 mm and confirm.
2. Place suspension at 100 mm and confirm.
3. Stream live sensor travel in mm.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
import statistics
import time

from mtb_telemetry.logging import append_csv_row, load_calibration, save_calibration, to_mm
from mtb_telemetry.sensors.ads1256 import ADS1256


CALIBRATION_FILE = Path("calibration/haltech_ads1256_ad0.json")
LOG_FILE = Path("data/haltech_travel.csv")


def sample_voltage(adc: ADS1256, sample_count: int = 40, channel: int = 0) -> float:
    """Return a stable voltage estimate using median of sampled readings."""
    values: list[float] = []
    for _ in range(sample_count):
        raw = adc.read_adc_raw_stable(channel=channel, samples=7)
        values.append(adc.raw_to_voltage(raw, vref=5.0, pga=1))
        time.sleep(0.01)
    return statistics.median(values)


def save_calibration_file(v_zero: float, v_hundred: float) -> None:
    """Persist calibration points to disk."""
    save_calibration(CALIBRATION_FILE, v_zero, v_hundred)


def load_calibration_file() -> tuple[float, float] | None:
    """Load calibration points if available and valid."""
    return load_calibration(CALIBRATION_FILE)


def perform_calibration(adc: ADS1256) -> tuple[float, float]:
    """Capture and save two-point calibration for 0 and 100 mm."""
    input("Set suspension to 0 mm (fully compressed), then press Enter...")
    v_zero = sample_voltage(adc, sample_count=50, channel=0)
    print(f"Captured 0 mm point: {v_zero:.4f} V")

    input("Set suspension to 100 mm (fully extended), then press Enter...")
    v_hundred = sample_voltage(adc, sample_count=50, channel=0)
    print(f"Captured 100 mm point: {v_hundred:.4f} V")

    span = v_hundred - v_zero
    print(f"Calibration span: {span:.4f} V")
    save_calibration_file(v_zero, v_hundred)
    print(f"Calibration saved: {CALIBRATION_FILE}")
    return v_zero, v_hundred


def main() -> None:
    """Run two-point calibration and stream live suspension travel in mm."""
    parser = argparse.ArgumentParser(description="Haltech ADS1256 two-point calibration and mm live output")
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="Ignore saved calibration and capture new 0/100 mm points.",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Append each reading to a CSV file in the data/ directory.",
    )
    args = parser.parse_args()

    adc = ADS1256()
    adc.open()

    try:
        adc.initialize_single_ended(enable_input_buffer=False)
        adc.prime_channel(channel=0, discard=10)

        calibration = None if args.recalibrate else load_calibration_file()
        if calibration is None:
            v_zero, v_hundred = perform_calibration(adc)
        else:
            v_zero, v_hundred = calibration
            span = v_hundred - v_zero
            print(f"Loaded calibration: {CALIBRATION_FILE}")
            print(f"  0 mm:   {v_zero:.4f} V")
            print(f"  100 mm: {v_hundred:.4f} V")
            print(f"  span:   {span:.4f} V")

        print("Live output in mm started. Stop with Ctrl+C.")
        if args.log:
            print(f"Logging to {LOG_FILE}")

        while True:
            raw = adc.read_adc_raw_stable(channel=0, samples=7)
            voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)
            travel_mm = to_mm(voltage, v_zero, v_hundred)
            clip_note = " [CLIP]" if raw >= ((1 << 23) - 1) else ""
            print(f"voltage={voltage:>7.4f} V  travel={travel_mm:>6.2f} mm{clip_note}")
            if args.log:
                timestamp = datetime.now(timezone.utc).isoformat()
                append_csv_row(
                    LOG_FILE,
                    {
                        "timestamp": timestamp,
                        "raw": raw,
                        "voltage": round(voltage, 6),
                        "travel_mm": round(travel_mm, 3),
                    },
                )
            time.sleep(0.05)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        adc.close()


if __name__ == "__main__":
    main()
