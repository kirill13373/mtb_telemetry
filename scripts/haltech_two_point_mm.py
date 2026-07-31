"""Two-point calibration and live mm output for Haltech travel sensor.

Workflow:
1. Place suspension at 0 mm and confirm.
2. Place suspension at 100 mm and confirm.
3. Stream live sensor travel in mm.
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

from mtb_telemetry.logging import load_calibration, save_calibration, to_mm
from mtb_telemetry.sensors.ads1256 import ADS1256


CALIBRATION_FILE = Path("calibration/haltech_ads1256_ad0.json")
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


def export_session_to_sufni(input_csv_path: Path) -> None:
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
            fieldnames=["timestamp", "raw", "voltage", "travel_mm"],
        )
        if self.path.stat().st_size == 0:
            self._writer.writeheader()
        self._rows_since_flush = 0

    def append(self, timestamp: str, raw: int, voltage: float, travel_mm: float) -> None:
        self._writer.writerow(
            {
                "timestamp": timestamp,
                "raw": raw,
                "voltage": round(voltage, 6),
                "travel_mm": round(travel_mm, 3),
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

    def __init__(self, gpio_pin: int, debounce_ms: int = 120, active_low: bool = True) -> None:
        if GPIO is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install python3-rpi.gpio or run on Raspberry Pi."
            )

        self.gpio_pin = gpio_pin
        self.active_low = active_low
        self.debounce_s = max(0.0, debounce_ms / 1000.0)

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        pull_mode = GPIO.PUD_UP if active_low else GPIO.PUD_DOWN
        GPIO.setup(self.gpio_pin, GPIO.IN, pull_up_down=pull_mode)

        self._last_stable_pressed = self._read_pressed_raw()
        self._last_raw_pressed = self._last_stable_pressed
        self._last_change_time = time.monotonic()

    def _read_pressed_raw(self) -> bool:
        level = GPIO.input(self.gpio_pin)
        return (level == GPIO.LOW) if self.active_low else (level == GPIO.HIGH)

    def consume_press_event(self) -> bool:
        """Return True exactly once per debounced button press edge."""
        now = time.monotonic()
        raw_pressed = self._read_pressed_raw()

        if raw_pressed != self._last_raw_pressed:
            self._last_raw_pressed = raw_pressed
            self._last_change_time = now

        if (now - self._last_change_time) < self.debounce_s:
            return False

        if raw_pressed != self._last_stable_pressed:
            self._last_stable_pressed = raw_pressed
            if raw_pressed:
                return True

        return False

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


def wait_for_stable_startup(
    adc: ADS1256,
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
        raw = adc.read_adc_raw_stable(channel=0, samples=7)
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
                f"Startup settled: window span={span:.4f} V "
                f"(range {v_min_expected:.3f}..{v_max_expected:.3f} V)"
            )
            return

    print(
        "Warning: startup did not fully stabilize before timeout; "
        "continuing with live output."
    )


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
        default=20.0,
        help=(
            "Target loop rate in Hz (default: 20). "
            "Set to 0 for maximum speed without extra pacing."
        ),
    )
    parser.add_argument(
        "--adc-samples",
        type=int,
        default=7,
        help=(
            "Median sample count per point (default: 7). "
            "Use 1 for highest possible rate (e.g. 500 Hz target)."
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

        expected_low = min(v_zero, v_hundred) - 0.35
        expected_high = max(v_zero, v_hundred) + 0.35
        print("Waiting for stable startup samples...")
        wait_for_stable_startup(adc, expected_low, expected_high)

        print("Live output in mm started. Stop with Ctrl+C.")
        if args.switch_gpio is not None:
            log_switch = LoggingSwitch(args.switch_gpio, debounce_ms=args.switch_debounce_ms)
            print(f"Switch logging control enabled on BCM GPIO {args.switch_gpio}.")
            print("Switch to GND => logging ON, other position => logging paused.")
            print(f"Debounce: {args.switch_debounce_ms} ms")
        elif args.button_gpio is not None:
            log_button = LoggingButton(args.button_gpio, debounce_ms=args.button_debounce_ms, active_low=True)
            print(f"Button logging control enabled on BCM GPIO {args.button_gpio}.")
            print("Wire button between GPIO and GND (internal pull-up active).")
            print("Each press toggles logging ON/OFF.")
            print(f"Debounce: {args.button_debounce_ms} ms")
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
            export_session_to_sufni(current_log_file)
            current_log_file = None
            prev_logging_enabled = False
            button_logging_enabled = False
            last_switch_state = False if log_switch is not None else last_switch_state

        sample_index = 0
        while True:
            loop_started = time.monotonic()
            if acquisition_start_monotonic is None:
                acquisition_start_monotonic = loop_started
                acquisition_start_utc = datetime.now(timezone.utc)

            if last_loop_started is not None:
                loop_interval = loop_started - last_loop_started
                loop_interval_sum_s += loop_interval
                loop_interval_count += 1
                if loop_interval_min_s is None or loop_interval < loop_interval_min_s:
                    loop_interval_min_s = loop_interval
                if loop_interval > loop_interval_max_s:
                    loop_interval_max_s = loop_interval
            last_loop_started = loop_started

            raw = adc.read_adc_raw_stable(channel=0, samples=args.adc_samples)
            voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)
            travel_mm = to_mm(voltage, v_zero, v_hundred)
            clip_note = " [CLIP]" if raw >= ((1 << 23) - 1) else ""
            sample_index += 1
            if not args.quiet and sample_index % args.print_every == 0:
                print(f"voltage={voltage:>7.4f} V  travel={travel_mm:>6.2f} mm{clip_note}")

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
                if log_button.consume_press_event():
                    button_logging_enabled = not button_logging_enabled
                    if button_logging_enabled:
                        current_log_file = build_session_log_file()
                        print(f"Logging ON -> {current_log_file}")
                    else:
                        print("Logging OFF")
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
                timestamp = datetime.now(timezone.utc).isoformat()
                if current_log_file is None:
                    current_log_file = build_session_log_file()
                if session_writer is None:
                    session_writer = SessionCsvWriter(current_log_file, flush_every=args.csv_flush_every)
                session_writer.append(timestamp=timestamp, raw=raw, voltage=voltage, travel_mm=travel_mm)
                logged_sample_count += 1

            loop_elapsed = time.monotonic() - loop_started
            if loop_elapsed > loop_elapsed_max_s:
                loop_elapsed_max_s = loop_elapsed

            if target_period_s > 0.0:
                remaining = target_period_s - loop_elapsed
                if remaining > 0.0:
                    time.sleep(remaining)
                else:
                    loop_overrun_count += 1
                    overrun_s = -remaining
                    if overrun_s > loop_overrun_max_s:
                        loop_overrun_max_s = overrun_s
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

        metrics_payload: dict[str, object] = {
            "run_started_utc": None
            if acquisition_start_utc is None
            else acquisition_start_utc.isoformat().replace("+00:00", "Z"),
            "run_ended_utc": run_ended_utc.isoformat().replace("+00:00", "Z"),
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

        if args.session_metrics_json is not None:
            try:
                write_metrics_report(args.session_metrics_json, metrics_payload)
                print(f"Metrics written: {args.session_metrics_json}")
            except OSError as exc:
                print(f"Failed to write metrics file: {exc}")

        if session_writer is not None:
            session_writer.close()
        if prev_logging_enabled and current_log_file is not None:
            export_session_to_sufni(current_log_file)
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
