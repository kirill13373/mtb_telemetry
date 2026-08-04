"""Two-point calibration and live mm output for shock + fork sensors.

Workflow:
1. Calibrate shock (AD0) at 0 mm and shock full-travel.
2. Calibrate fork (AD1) at 0 mm and fork full-travel.
3. Stream both sensor travels in mm.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import statistics
import sys
import time

def _load_gpio_module():
    """Load RPi.GPIO from venv or fallback to system dist-packages on Raspberry Pi."""
    try:
        import RPi.GPIO as rpi_gpio

        return rpi_gpio
    except ImportError:
        # Common on venvs created without --system-site-packages.
        for path in (
            "/usr/lib/python3/dist-packages",
            "/usr/local/lib/python3.13/dist-packages",
            "/usr/local/lib/python3/dist-packages",
        ):
            if path not in sys.path and Path(path).exists():
                sys.path.append(path)

        try:
            import RPi.GPIO as rpi_gpio

            return rpi_gpio
        except ImportError:
            return None


GPIO = _load_gpio_module()

from mtb_telemetry.logging import load_calibration, save_calibration
from mtb_telemetry.sensors.ads1256 import ADS1256


CALIBRATION_FILE_SHOCK = Path("calibration/haltech_ads1256_ad0.json")
CALIBRATION_FILE_FORK = Path("calibration/haltech_ads1256_ad1.json")
LOG_DIR = Path("data")
SUFNI_DIR = LOG_DIR / "sufni"
LOG_FILE_PREFIX = "haltech_travel"
LOG_FILE = LOG_DIR / "haltech_travel.csv"
SHUTDOWN_COMMAND_CANDIDATES = (
    "/usr/sbin/shutdown",
    "/sbin/shutdown",
    "shutdown",
)


def build_session_log_file(now_utc: datetime | None = None) -> Path:
    """Return a unique CSV path for one recording session."""
    if now_utc is None:
        now_utc = datetime.now(timezone.utc)
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    return LOG_DIR / f"{LOG_FILE_PREFIX}_{stamp}.csv"


def build_sufni_output_paths(input_csv_path: Path) -> tuple[Path, Path]:
    """Build Sufni output and metadata paths based on the source session CSV."""
    stem = input_csv_path.stem
    output_csv = SUFNI_DIR / f"{stem}_sufni.csv"
    output_meta = SUFNI_DIR / f"{stem}_sufni_meta.json"
    return output_csv, output_meta


def export_session_to_sufni(
    input_csv_path: Path,
    session_start_utc: datetime | None = None,
) -> None:
    """Run the Sufni export script for one recorded session CSV."""
    if not input_csv_path.exists() or input_csv_path.stat().st_size == 0:
        print(f"Skip Sufni export (no data): {input_csv_path}")
        return

    export_script = Path(__file__).with_name("export_sufni_csv.py")
    if not export_script.exists():
        print(f"Sufni export script missing: {export_script}")
        return

    output_csv, output_meta = build_sufni_output_paths(input_csv_path)
    command = [
        sys.executable,
        str(export_script),
        "--input",
        str(input_csv_path),
        "--output",
        str(output_csv),
        "--metadata",
        str(output_meta),
    ]
    if session_start_utc is not None:
        command += [
            "--session-start-utc",
            session_start_utc.isoformat().replace("+00:00", "Z"),
        ]

    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
        print(f"Sufni export done: {output_csv}")
        if result.stdout.strip():
            print(result.stdout.strip())
    except subprocess.CalledProcessError as exc:
        print(f"Sufni export failed for {input_csv_path}: {exc}")
        if exc.stdout:
            print(exc.stdout.strip())
        if exc.stderr:
            print(exc.stderr.strip())


def request_system_shutdown() -> None:
    """Trigger an orderly Raspberry Pi shutdown via sudo."""
    last_error: subprocess.CalledProcessError | None = None
    for executable in SHUTDOWN_COMMAND_CANDIDATES:
        if "/" in executable and not Path(executable).exists():
            continue

        command = ["sudo", executable, "-h", "now"]
        try:
            subprocess.run(command, check=True)
            return
        except FileNotFoundError:
            continue
        except subprocess.CalledProcessError as exc:
            last_error = exc
            break

    if last_error is not None:
        raise RuntimeError(
            "Failed to trigger shutdown. "
            "Ensure the service user may run shutdown via sudo without a password."
        ) from last_error

    raise RuntimeError("No shutdown executable found on this system.")


def write_metrics_report(path: Path, payload: dict[str, object]) -> None:
    """Persist runtime metrics for benchmark comparisons."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


class SessionCsvWriter:
    """Buffered CSV writer for high-rate logging without per-row file reopen."""

    def __init__(self, path: Path, flush_every: int = 100) -> None:
        self.path = path
        self.flush_every = max(1, flush_every)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = self.path.open("a", encoding="utf-8", newline="")
        self._writer = csv.DictWriter(
            self._handle,
            fieldnames=[
                "timestamp",
                "shock_raw",
                "shock_voltage",
                "shock_travel_mm",
                "fork_raw",
                "fork_voltage",
                "fork_travel_mm",
            ],
        )
        if self.path.stat().st_size == 0:
            self._writer.writeheader()
        self._rows_since_flush = 0

    def append(
        self,
        timestamp: str,
        shock_raw: int,
        shock_voltage: float,
        shock_travel_mm: float,
        fork_raw: int,
        fork_voltage: float,
        fork_travel_mm: float,
    ) -> None:
        self._writer.writerow(
            {
                "timestamp": timestamp,
                "shock_raw": shock_raw,
                "shock_voltage": round(shock_voltage, 6),
                "shock_travel_mm": round(shock_travel_mm, 3),
                "fork_raw": fork_raw,
                "fork_voltage": round(fork_voltage, 6),
                "fork_travel_mm": round(fork_travel_mm, 3),
            }
        )
        self._rows_since_flush += 1
        if self._rows_since_flush >= self.flush_every:
            self._handle.flush()
            self._rows_since_flush = 0

    def close(self) -> None:
        self._handle.flush()
        self._handle.close()


class LoggingSwitch:
    """GPIO-backed toggle switch using internal pull-up (active-low)."""

    def __init__(self, gpio_pin: int, debounce_ms: int = 250) -> None:
        if GPIO is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install python3-rpi.gpio or run on Raspberry Pi."
            )

        self.gpio_pin = gpio_pin
        self.debounce_s = max(0.0, debounce_ms / 1000.0)
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=GPIO.PUD_UP)

        self._last_raw_state = self._read_raw_state()
        self._debounced_state = self._last_raw_state
        self._last_change_time = time.monotonic()

    def _read_raw_state(self) -> bool:
        """Return raw switch state (True when switch is in GND position)."""
        return GPIO.input(self.gpio_pin) == GPIO.LOW

    def is_logging_enabled(self) -> bool:
        """Return debounced switch state (True when switch is in GND position)."""
        now = time.monotonic()
        raw_state = self._read_raw_state()

        if raw_state != self._last_raw_state:
            self._last_raw_state = raw_state
            self._last_change_time = now

        if raw_state != self._debounced_state and (now - self._last_change_time) >= self.debounce_s:
            self._debounced_state = raw_state

        return self._debounced_state

    def close(self) -> None:
        """Release only this GPIO pin during shutdown."""
        GPIO.cleanup(self.gpio_pin)


class LoggingButton:
    """GPIO-backed momentary button with debounced press event detection."""

    def __init__(
        self,
        gpio_pin: int,
        debounce_ms: int = 120,
        active_low: bool = True,
        long_press_ms: int = 1500,
    ) -> None:
        if GPIO is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install python3-rpi.gpio or run on Raspberry Pi."
            )

        self.gpio_pin = gpio_pin
        self.active_low = active_low
        self.debounce_s = max(0.0, debounce_ms / 1000.0)
        self.long_press_s = max(self.debounce_s, long_press_ms / 1000.0)

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        pull_mode = GPIO.PUD_UP if active_low else GPIO.PUD_DOWN
        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=pull_mode)

        self._last_stable_pressed = self._read_pressed_raw()
        self._last_raw_pressed = self._last_stable_pressed
        self._last_change_time = time.monotonic()
        self._press_started_at: float | None = time.monotonic() if self._last_stable_pressed else None

    def _read_pressed_raw(self) -> bool:
        level = GPIO.input(self.gpio_pin)
        return (level == GPIO.LOW) if self.active_low else (level == GPIO.HIGH)

    def consume_event(self) -> str | None:
        """Return `short_press` or `long_press` once per debounced press cycle."""
        now = time.monotonic()
        raw_pressed = self._read_pressed_raw()

        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_change_time = now

        if (now - self._last_change_time) < self.debounce_s:
            return None

        if raw_pressed != self._last_stable_pressed:
            self._last_stable_pressed = raw_pressed
            if raw_pressed:
                self._press_started_at = now
            else:
                if self._press_started_at is None:
                    return None
                pressed_for_s = now - self._press_started_at
                self._press_started_at = None
                if pressed_for_s >= self.long_press_s:
                    return "long_press"
                return "short_press"

        return None

    def consume_press_event(self) -> bool:
        """Return True once per debounced press, regardless of short/long press."""
        return self.consume_event() is not None

    def close(self) -> None:
        """Release only this GPIO pin during shutdown."""
        GPIO.cleanup(self.gpio_pin)


class StatusLed:
    """GPIO-backed status LED that reflects measurement logging state."""

    def __init__(self, gpio_pin: int, active_high: bool = True) -> None:
        if GPIO is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install python3-rpi.gpio or run on Raspberry Pi."
            )

        self.gpio_pin = gpio_pin
        self.active_high = active_high
        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.gpio_pin, GPIO.OUT, initial=GPIO.LOW)
        self.set_enabled(False)

    def set_enabled(self, enabled: bool) -> None:
        """Set LED state; True means measurement logging is active."""
        output_high = enabled if self.active_high else (not enabled)
        GPIO.output(self.gpio_pin, GPIO.HIGH if output_high else GPIO.LOW)

    def close(self) -> None:
        """Turn LED off and release only this GPIO pin."""
        self.set_enabled(False)
        GPIO.cleanup(self.gpio_pin)


def sample_voltage(adc: ADS1256, sample_count: int = 40, channel: int = 0) -> float:
    """Return a stable voltage estimate using median of sampled readings."""
    values: list[float] = []
    for _ in range(sample_count):
        raw = adc.read_adc_raw_stable(channel=channel, samples=7)
        values.append(adc.raw_to_voltage(raw, vref=5.0, pga=1))
        time.sleep(0.01)
    return statistics.median(values)


def save_calibration_file(path: Path, v_zero: float, v_hundred: float) -> None:
    """Persist calibration points to disk."""
    save_calibration(path, v_zero, v_hundred)


def load_calibration_file(path: Path) -> tuple[float, float] | None:
    """Load calibration points if available and valid."""
    return load_calibration(path)


def to_mm_with_range(voltage: float, v_zero: float, v_full: float, full_scale_mm: float) -> float:
    """Map voltage linearly from [v_zero, v_full] to [0, full_scale_mm] mm."""
    span = v_full - v_zero
    if abs(span) < 0.01:
        raise ValueError("Calibration span is too small. Check sensor movement and wiring.")
    mm = (voltage - v_zero) * (full_scale_mm / span)
    return max(0.0, min(full_scale_mm, mm))


def perform_session_baseline(
    adc: ADS1256,
    sensor_name: str,
    channel: int,
    v_zero_ref: float,
    v_full_ref: float,
) -> tuple[float, float]:
    """Re-anchor one session from a fully-extended measurement only.

    The stored calibration span is preserved. A long button press is used to
    tell the rider to lift the bike so the suspension sits at its unloaded,
    fully extended ride state.
    """
    reference_span = v_full_ref - v_zero_ref
    print(
        f"Calibrating {sensor_name} baseline. Lift bike so the suspension is fully extended "
        "(not the sensor by itself)..."
    )
    time.sleep(0.35)
    session_v_full = sample_voltage(adc, sample_count=35, channel=channel)
    session_v_zero = session_v_full - reference_span
    drift_v = session_v_full - v_full_ref
    print(
        f"{sensor_name} baseline updated: extended={session_v_full:.4f} V "
        f"(drift {drift_v:+.4f} V, span {reference_span:.4f} V)"
    )
    return session_v_zero, session_v_full


def perform_calibration(
    adc: ADS1256,
    sensor_name: str,
    channel: int,
    calibration_path: Path,
    full_travel_mm: float,
) -> tuple[float, float]:
    """Capture and save two-point calibration for 0 mm and full travel."""
    input(f"Set {sensor_name} to 0 mm (fully compressed), then press Enter...")
    v_zero = sample_voltage(adc, sample_count=50, channel=channel)
    print(f"Captured {sensor_name} 0 mm point: {v_zero:.4f} V")

    input(
        f"Set {sensor_name} to {full_travel_mm:.0f} mm "
        "(fully extended), then press Enter..."
    )
    v_hundred = sample_voltage(adc, sample_count=50, channel=channel)
    print(f"Captured {sensor_name} {full_travel_mm:.0f} mm point: {v_hundred:.4f} V")

    span = v_hundred - v_zero
    print(f"{sensor_name} calibration span: {span:.4f} V")
    save_calibration_file(calibration_path, v_zero, v_hundred)
    print(f"Calibration saved: {calibration_path}")
    return v_zero, v_hundred


def wait_for_stable_startup(
    adc: ADS1256,
    sensor_name: str,
    channel: int,
    v_min_expected: float,
    v_max_expected: float,
    max_wait_s: float = 4.0,
    window_size: int = 12,
) -> None:
    """Wait until startup samples are plausible and stable before live output.

    This avoids logging/printing the known cold-start transients that can appear
    for the first few reads.
    """
    deadline = time.time() + max_wait_s
    window: list[float] = []

    while time.time() < deadline:
        raw = adc.read_adc_raw_stable(channel=channel, samples=7)
        voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)
        window.append(voltage)
        if len(window) > window_size:
            window.pop(0)

        if len(window) < window_size:
            continue

        in_range = all(v_min_expected <= value <= v_max_expected for value in window)
        span = max(window) - min(window)
        if in_range and span < 0.12:
            print(
                f"{sensor_name} startup settled: window span={span:.4f} V "
                f"(range {v_min_expected:.3f}..{v_max_expected:.3f} V)"
            )
            return

    print(
        f"Warning: {sensor_name} startup did not fully stabilize before timeout; "
        "continuing with live output."
    )


def main() -> None:
    """Run two-point calibration and stream live shock/fork travel in mm."""
    parser = argparse.ArgumentParser(description="Haltech ADS1256 two-point calibration and mm live output")
    parser.add_argument(
        "--recalibrate",
        action="store_true",
        help="Ignore saved calibration and capture new 0/full-travel points.",
    )
    parser.add_argument(
        "--shock-travel-mm-max",
        type=float,
        default=100.0,
        help="Shock full-travel reference in mm (default: 100).",
    )
    parser.add_argument(
        "--fork-travel-mm-max",
        type=float,
        default=200.0,
        help="Fork full-travel reference in mm (default: 200).",
    )
    parser.add_argument(
        "--log",
        action="store_true",
        help="Append each reading to a CSV file in the data/ directory.",
    )
    parser.add_argument(
        "--switch-gpio",
        type=int,
        default=None,
        help=(
            "Optional BCM GPIO pin for active-low log control switch. "
            "Switch to GND = logging ON, open = logging paused."
        ),
    )
    parser.add_argument(
        "--switch-debounce-ms",
        type=int,
        default=250,
        help="Debounce time for --switch-gpio in milliseconds (default: 250).",
    )
    parser.add_argument(
        "--button-gpio",
        type=int,
        default=None,
        help=(
            "Optional BCM GPIO pin for momentary button log control. "
            "Each press toggles logging on/off."
        ),
    )
    parser.add_argument(
        "--button-debounce-ms",
        type=int,
        default=120,
        help="Debounce time for --button-gpio in milliseconds (default: 120).",
    )
    parser.add_argument(
        "--button-long-press-ms",
        type=int,
        default=2500,
        help=(
            "Hold time for --button-gpio to trigger per-session baseline calibration "
            "instead of logging toggle (default: 2500)."
        ),
    )
    parser.add_argument(
        "--shutdown-button-gpio",
        type=int,
        default=None,
        help=(
            "Optional BCM GPIO pin for a dedicated shutdown button. "
            "Pressing it closes the active log cleanly and powers off the Raspberry Pi."
        ),
    )
    parser.add_argument(
        "--shutdown-button-debounce-ms",
        type=int,
        default=800,
        help="Debounce time for --shutdown-button-gpio in milliseconds (default: 800).",
    )
    parser.add_argument(
        "--status-led-gpio",
        type=int,
        default=None,
        help=(
            "Optional BCM GPIO pin for a status LED. "
            "LED is ON while measurement logging is active and OFF otherwise."
        ),
    )
    parser.add_argument(
        "--status-led-active-low",
        action="store_true",
        help="Invert LED output logic for active-low LED modules.",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="Disable per-sample terminal output (useful for headless/background operation).",
    )
    parser.add_argument(
        "--print-every",
        type=int,
        default=1,
        help="Print every Nth sample in terminal output (default: 1). Ignored with --quiet.",
    )
    parser.add_argument(
        "--target-hz",
        type=float,
        default=500.0,
        help=(
            "Target loop rate in Hz (default: 500). "
            "Set to 0 for maximum speed without extra pacing."
        ),
    )
    parser.add_argument(
        "--adc-samples",
        type=int,
        default=1,
        help=(
            "Median sample count per point (default: 1). "
            "Use 1 for highest possible rate at 500 Hz target."
        ),
    )
    parser.add_argument(
        "--csv-flush-every",
        type=int,
        default=120,
        help="Flush CSV after N rows (default: 120).",
    )
    parser.add_argument(
        "--session-metrics-json",
        type=Path,
        default=None,
        help=(
            "Optional output path for runtime metrics JSON. "
            "Useful for repeatable 500 Hz benchmark runs."
        ),
    )
    args = parser.parse_args()
    if args.print_every < 1:
        parser.error("--print-every must be at least 1")
    if args.target_hz < 0:
        parser.error("--target-hz must be >= 0")
    if args.adc_samples < 1:
        parser.error("--adc-samples must be at least 1")
    if args.csv_flush_every < 1:
        parser.error("--csv-flush-every must be at least 1")
    if args.button_long_press_ms < 250:
        parser.error("--button-long-press-ms must be at least 250")
    if args.shock_travel_mm_max <= 0:
        parser.error("--shock-travel-mm-max must be > 0")
    if args.fork_travel_mm_max <= 0:
        parser.error("--fork-travel-mm-max must be > 0")
    if args.switch_gpio is not None and args.button_gpio is not None:
        parser.error("Use either --switch-gpio or --button-gpio, not both")
    if args.shutdown_button_gpio is not None and (
        args.shutdown_button_gpio == args.switch_gpio or args.shutdown_button_gpio == args.button_gpio
    ):
        parser.error("--shutdown-button-gpio must be different from the log control GPIO")
    if args.status_led_gpio is not None and args.status_led_gpio in {
        args.switch_gpio,
        args.button_gpio,
        args.shutdown_button_gpio,
    }:
        parser.error("--status-led-gpio must be different from button/switch GPIOs")

    fast_channel_switching = args.target_hz >= 500 and args.adc_samples == 1

    waveshare_reserved_gpios = {17, 18, 22, 23, 27}
    control_gpios = {
        "--switch-gpio": args.switch_gpio,
        "--button-gpio": args.button_gpio,
        "--shutdown-button-gpio": args.shutdown_button_gpio,
        "--status-led-gpio": args.status_led_gpio,
    }
    for option, gpio in control_gpios.items():
        if gpio in waveshare_reserved_gpios:
            parser.error(
                f"{option} BCM GPIO {gpio} is reserved by the Waveshare AD/DA HAT "
                "(DRDY=17, RESET=18, ADS_CS=22, DAC_CS=23, PDWN=27)"
            )

    target_period_s = 0.0 if args.target_hz == 0 else (1.0 / args.target_hz)

    adc = ADS1256()
    adc.open()
    log_switch: LoggingSwitch | None = None
    log_button: LoggingButton | None = None
    shutdown_button: LoggingButton | None = None
    status_led: StatusLed | None = None
    last_switch_state: bool | None = None
    button_logging_enabled = bool(args.log)
    prev_logging_enabled = False
    current_log_file: Path | None = None
    session_writer: SessionCsvWriter | None = None
    acquisition_start_monotonic: float | None = None
    acquisition_start_utc: datetime | None = None
    last_loop_started: float | None = None
    loop_interval_sum_s = 0.0
    loop_interval_count = 0
    loop_interval_min_s: float | None = None
    loop_interval_max_s = 0.0
    loop_elapsed_max_s = 0.0
    loop_overrun_count = 0
    loop_overrun_max_s = 0.0
    logged_sample_count = 0

    def build_metrics_payload(run_ended_utc: datetime, reason: str) -> dict[str, object]:
        """Build a consistent metrics payload for JSON reporting."""
        duration_s = 0.0
        effective_loop_hz = 0.0
        if acquisition_start_monotonic is not None:
            duration_s = max(0.0, time.monotonic() - acquisition_start_monotonic)
        if duration_s > 0.0 and sample_index > 0:
            effective_loop_hz = sample_index / duration_s

        mean_loop_interval_s: float | None = None
        if loop_interval_count > 0:
            mean_loop_interval_s = loop_interval_sum_s / loop_interval_count

        return {
            "run_started_utc": None
            if acquisition_start_utc is None
            else acquisition_start_utc.isoformat().replace("+00:00", "Z"),
            "run_ended_utc": run_ended_utc.isoformat().replace("+00:00", "Z"),
            "report_reason": reason,
            "target_hz": args.target_hz,
            "adc_samples": args.adc_samples,
            "csv_flush_every": args.csv_flush_every,
            "samples_total": sample_index,
            "samples_logged": logged_sample_count,
            "duration_s": round(duration_s, 6),
            "effective_loop_hz": round(effective_loop_hz, 6),
            "loop_overruns": loop_overrun_count,
            "max_overrun_s": round(loop_overrun_max_s, 6),
            "max_loop_elapsed_s": round(loop_elapsed_max_s, 6),
            "mean_loop_interval_s": None
            if mean_loop_interval_s is None
            else round(mean_loop_interval_s, 6),
            "min_loop_interval_s": None
            if loop_interval_min_s is None
            else round(loop_interval_min_s, 6),
            "max_loop_interval_s": round(loop_interval_max_s, 6),
            "logging_mode": "switch"
            if args.switch_gpio is not None
            else ("button" if args.button_gpio is not None else "always_on"),
        }

    def write_metrics_if_enabled(reason: str) -> None:
        if args.session_metrics_json is None:
            return

        payload = build_metrics_payload(datetime.now(timezone.utc), reason)
        try:
            write_metrics_report(args.session_metrics_json, payload)
            print(f"Metrics written ({reason}): {args.session_metrics_json}")
        except OSError as exc:
            print(f"Failed to write metrics file: {exc}")

    try:
        adc.initialize_single_ended(enable_input_buffer=False)
        adc.prime_channel(channel=0, discard=10)
        adc.prime_channel(channel=1, discard=10)

        shock_calibration = None if args.recalibrate else load_calibration_file(CALIBRATION_FILE_SHOCK)
        if shock_calibration is None:
            shock_v_zero, shock_v_hundred = perform_calibration(
                adc,
                sensor_name="shock",
                channel=0,
                calibration_path=CALIBRATION_FILE_SHOCK,
                full_travel_mm=args.shock_travel_mm_max,
            )
        else:
            shock_v_zero, shock_v_hundred = shock_calibration
            span = shock_v_hundred - shock_v_zero
            print(f"Loaded shock calibration: {CALIBRATION_FILE_SHOCK}")
            print(f"  0 mm:   {shock_v_zero:.4f} V")
            print(f"  100 mm: {shock_v_hundred:.4f} V")
            print(f"  span:   {span:.4f} V")

        fork_calibration = None if args.recalibrate else load_calibration_file(CALIBRATION_FILE_FORK)
        if fork_calibration is None:
            fork_v_zero, fork_v_hundred = perform_calibration(
                adc,
                sensor_name="fork",
                channel=1,
                calibration_path=CALIBRATION_FILE_FORK,
                full_travel_mm=args.fork_travel_mm_max,
            )
        else:
            fork_v_zero, fork_v_hundred = fork_calibration
            span = fork_v_hundred - fork_v_zero
            print(f"Loaded fork calibration: {CALIBRATION_FILE_FORK}")
            print(f"  0 mm:   {fork_v_zero:.4f} V")
            print(f"  100 mm: {fork_v_hundred:.4f} V")
            print(f"  span:   {span:.4f} V")

        print("Waiting for stable startup samples...")
        shock_expected_low = min(shock_v_zero, shock_v_hundred) - 0.35
        shock_expected_high = max(shock_v_zero, shock_v_hundred) + 0.35
        wait_for_stable_startup(
            adc,
            sensor_name="Shock",
            channel=0,
            v_min_expected=shock_expected_low,
            v_max_expected=shock_expected_high,
        )

        fork_expected_low = min(fork_v_zero, fork_v_hundred) - 0.35
        fork_expected_high = max(fork_v_zero, fork_v_hundred) + 0.35
        wait_for_stable_startup(
            adc,
            sensor_name="Fork",
            channel=1,
            v_min_expected=fork_expected_low,
            v_max_expected=fork_expected_high,
        )

        print("Live output in mm started. Stop with Ctrl+C.")
        if fast_channel_switching:
            print("Fast channel switching enabled for 500 Hz streaming (no extra post-MUX discard).")
        if args.switch_gpio is not None:
            log_switch = LoggingSwitch(args.switch_gpio, debounce_ms=args.switch_debounce_ms)
            print(f"Switch logging control enabled on BCM GPIO {args.switch_gpio}.")
            print("Switch to GND => logging ON, other position => logging paused.")
            print(f"Debounce: {args.switch_debounce_ms} ms")
        elif args.button_gpio is not None:
            log_button = LoggingButton(
                args.button_gpio,
                debounce_ms=args.button_debounce_ms,
                active_low=True,
                long_press_ms=args.button_long_press_ms,
            )
            print(f"Button logging control enabled on BCM GPIO {args.button_gpio}.")
            print("Wire button between GPIO and GND (internal pull-up active).")
            print("Short press toggles logging ON/OFF.")
            print("Long press recalibrates the current session baseline (bike lifted).")
            print(f"Debounce: {args.button_debounce_ms} ms")
            print(f"Long press: {args.button_long_press_ms} ms")
            print(f"Initial logging state: {'ON' if button_logging_enabled else 'OFF'}")
        elif args.log:
            print(f"Logging to {LOG_FILE}")

        if args.shutdown_button_gpio is not None:
            shutdown_button = LoggingButton(
                args.shutdown_button_gpio,
                debounce_ms=args.shutdown_button_debounce_ms,
                active_low=True,
            )
            print(f"Shutdown button enabled on BCM GPIO {args.shutdown_button_gpio}.")
            print("Wire shutdown button between GPIO and GND (internal pull-up active).")
            print("Pressing it will close the current log and shut down the Raspberry Pi.")
            print(f"Debounce: {args.shutdown_button_debounce_ms} ms")

        if args.status_led_gpio is not None:
            status_led = StatusLed(
                args.status_led_gpio,
                active_high=not args.status_led_active_low,
            )
            print(f"Status LED enabled on BCM GPIO {args.status_led_gpio}.")
            print("LED is ON while logging is active and OFF while paused.")
            print(f"Output mode: {'active-low' if args.status_led_active_low else 'active-high'}")

        def close_active_writer() -> None:
            nonlocal session_writer
            if session_writer is not None:
                session_writer.close()
                session_writer = None

        def finalize_active_session() -> None:
            nonlocal current_log_file, prev_logging_enabled, button_logging_enabled, last_switch_state
            if current_log_file is None:
                return

            close_active_writer()
            write_metrics_if_enabled("session_finalized")
            export_session_to_sufni(current_log_file, session_start_utc=acquisition_start_utc)
            current_log_file = None
            prev_logging_enabled = False
            button_logging_enabled = False
            last_switch_state = False if log_switch is not None else last_switch_state

        # Spinwait threshold: sleep for (remaining - SPINWAIT_S), then busy-wait
        # for the last slice.  This avoids OS scheduler overshoot (~0.07 ms on Pi)
        # that prevents time.sleep() alone from reaching 500 Hz.
        SPINWAIT_S = 0.0008  # 0.8 ms: safe margin above max observed loop work

        sample_index = 0
        next_deadline = 0.0  # initialised on first iteration
        while True:
            loop_started = time.monotonic()
            if acquisition_start_monotonic is None:
                acquisition_start_monotonic = loop_started
                acquisition_start_utc = datetime.now(timezone.utc)
                next_deadline = loop_started

            if last_loop_started is not None:
                loop_interval = loop_started - last_loop_started
                loop_interval_sum_s += loop_interval
                loop_interval_count += 1
                if loop_interval_min_s is None or loop_interval < loop_interval_min_s:
                    loop_interval_min_s = loop_interval
                if loop_interval > loop_interval_max_s:
                    loop_interval_max_s = loop_interval
            last_loop_started = loop_started

            shock_raw = adc.read_adc_raw_stable(
                channel=0,
                samples=args.adc_samples,
                discard_first_after_mux=not fast_channel_switching,
            )
            shock_voltage = adc.raw_to_voltage(shock_raw, vref=5.0, pga=1)
            shock_travel_mm = to_mm_with_range(
                shock_voltage,
                shock_v_zero,
                shock_v_hundred,
                args.shock_travel_mm_max,
            )

            fork_raw = adc.read_adc_raw_stable(
                channel=1,
                samples=args.adc_samples,
                discard_first_after_mux=not fast_channel_switching,
            )
            fork_voltage = adc.raw_to_voltage(fork_raw, vref=5.0, pga=1)
            fork_travel_mm = to_mm_with_range(
                fork_voltage,
                fork_v_zero,
                fork_v_hundred,
                args.fork_travel_mm_max,
            )

            shock_clip_note = " [S_CLIP]" if shock_raw >= ((1 << 23) - 1) else ""
            fork_clip_note = " [F_CLIP]" if fork_raw >= ((1 << 23) - 1) else ""
            sample_index += 1
            if not args.quiet and sample_index % args.print_every == 0:
                print(
                    "shock="
                    f"{shock_voltage:>7.4f} V/{shock_travel_mm:>6.2f} mm"
                    f"{shock_clip_note}  "
                    "fork="
                    f"{fork_voltage:>7.4f} V/{fork_travel_mm:>6.2f} mm"
                    f"{fork_clip_note}"
                )

            logging_enabled = args.log
            if log_switch is not None:
                switch_state = log_switch.is_logging_enabled()
                logging_enabled = switch_state
                if switch_state != last_switch_state:
                    if switch_state:
                        current_log_file = build_session_log_file()
                        print(f"Logging ON -> {current_log_file}")
                    else:
                        print("Logging OFF")
                    last_switch_state = switch_state
            elif log_button is not None:
                button_event = log_button.consume_event()
                if button_event == "short_press":
                    button_logging_enabled = not button_logging_enabled
                    if button_logging_enabled:
                        current_log_file = build_session_log_file()
                        print(f"Logging ON -> {current_log_file}")
                    else:
                        print("Logging OFF")
                elif button_event == "long_press":
                    if button_logging_enabled:
                        print("Ignore long press while logging is active. Stop logging first.")
                    else:
                        shock_v_zero, shock_v_hundred = perform_session_baseline(
                            adc,
                            sensor_name="Shock",
                            channel=0,
                            v_zero_ref=shock_v_zero,
                            v_full_ref=shock_v_hundred,
                        )
                        fork_v_zero, fork_v_hundred = perform_session_baseline(
                            adc,
                            sensor_name="Fork",
                            channel=1,
                            v_zero_ref=fork_v_zero,
                            v_full_ref=fork_v_hundred,
                        )
                logging_enabled = button_logging_enabled

            if shutdown_button is not None and shutdown_button.consume_press_event():
                print("Shutdown button pressed. Finalizing active session...")
                if current_log_file is not None:
                    finalize_active_session()
                try:
                    request_system_shutdown()
                except RuntimeError as exc:
                    print(f"Shutdown request failed: {exc}")
                else:
                    print("Shutdown requested.")
                    break

            if prev_logging_enabled and not logging_enabled and current_log_file is not None:
                finalize_active_session()

            if status_led is not None:
                status_led.set_enabled(logging_enabled)

            if logging_enabled:
                # Store monotonic offset from session start instead of
                # formatting a UTC ISO string per sample (expensive in hot path).
                # UTC timestamps are reconstructed during export.
                if current_log_file is None:
                    current_log_file = build_session_log_file()
                if session_writer is None:
                    session_writer = SessionCsvWriter(current_log_file, flush_every=args.csv_flush_every)
                mono_offset_s = loop_started - acquisition_start_monotonic
                session_writer.append(
                    timestamp=f"{mono_offset_s:.6f}",
                    shock_raw=shock_raw,
                    shock_voltage=shock_voltage,
                    shock_travel_mm=shock_travel_mm,
                    fork_raw=fork_raw,
                    fork_voltage=fork_voltage,
                    fork_travel_mm=fork_travel_mm,
                )
                logged_sample_count += 1

            loop_elapsed = time.monotonic() - loop_started
            if loop_elapsed > loop_elapsed_max_s:
                loop_elapsed_max_s = loop_elapsed

            if target_period_s > 0.0:
                next_deadline += target_period_s
                now = time.monotonic()
                sleep_s = next_deadline - now - SPINWAIT_S
                if sleep_s > 0.0:
                    time.sleep(sleep_s)
                # Spinwait for the remaining slice (SPINWAIT_S window)
                while time.monotonic() < next_deadline:
                    pass
                # Deadline overrun check
                overrun_s = time.monotonic() - next_deadline
                if overrun_s > 0.001:  # only count meaningful overruns (> 1 ms)
                    loop_overrun_count += 1
                    if overrun_s > loop_overrun_max_s:
                        loop_overrun_max_s = overrun_s
                    # Re-sync deadline to avoid cascading overruns
                    next_deadline = time.monotonic()
            prev_logging_enabled = logging_enabled
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        run_ended_utc = datetime.now(timezone.utc)
        duration_s = 0.0
        effective_loop_hz = 0.0
        if acquisition_start_monotonic is not None:
            duration_s = max(0.0, time.monotonic() - acquisition_start_monotonic)
        if duration_s > 0.0 and sample_index > 0:
            effective_loop_hz = sample_index / duration_s

        mean_loop_interval_s: float | None = None
        if loop_interval_count > 0:
            mean_loop_interval_s = loop_interval_sum_s / loop_interval_count

        print("Run metrics:")
        print(f"  samples_total: {sample_index}")
        print(f"  samples_logged: {logged_sample_count}")
        print(f"  duration_s: {duration_s:.3f}")
        if effective_loop_hz > 0.0:
            print(f"  effective_loop_hz: {effective_loop_hz:.2f}")
        if target_period_s > 0.0:
            print(f"  target_hz: {args.target_hz:.3f}")
        print(f"  loop_overruns: {loop_overrun_count}")
        print(f"  max_overrun_ms: {loop_overrun_max_s * 1000.0:.3f}")
        print(f"  max_loop_elapsed_ms: {loop_elapsed_max_s * 1000.0:.3f}")
        if mean_loop_interval_s is not None:
            print(f"  mean_loop_interval_ms: {mean_loop_interval_s * 1000.0:.3f}")
            if loop_interval_min_s is not None:
                print(f"  min_loop_interval_ms: {loop_interval_min_s * 1000.0:.3f}")
            print(f"  max_loop_interval_ms: {loop_interval_max_s * 1000.0:.3f}")

        write_metrics_if_enabled("run_ended")

        if session_writer is not None:
            session_writer.close()
        if prev_logging_enabled and current_log_file is not None:
            export_session_to_sufni(current_log_file, session_start_utc=acquisition_start_utc)
        if log_switch is not None:
            log_switch.close()
        if log_button is not None:
            log_button.close()
        if shutdown_button is not None:
            shutdown_button.close()
        if status_led is not None:
            status_led.close()
        adc.close()


if __name__ == "__main__":
    main()
