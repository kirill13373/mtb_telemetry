from __future__ import annotations

from pathlib import Path

import pytest

from mtb_telemetry.logging import append_csv_row, load_calibration, save_calibration, to_mm


class FakeGPIO:
    BCM = 1
    IN = 0
    OUT = 1
    LOW = 0
    HIGH = 1
    PUD_UP = 2
    PUD_DOWN = 3

    def __init__(self) -> None:
        self.inputs: dict[int, int] = {}
        self.mode: int | None = None
        self.setups: list[tuple[int, int, int | None]] = []
        self.cleaned: list[int] = []

    def setwarnings(self, _flag: bool) -> None:
        return None

    def setmode(self, mode: int) -> None:
        self.mode = mode

    def setup(self, pin: int, direction: int, pull_up_down: int | None = None) -> None:
        self.setups.append((pin, direction, pull_up_down))

    def input(self, pin: int) -> int:
        return self.inputs.get(pin, self.HIGH)

    def output(self, pin: int, value: int) -> None:
        self.inputs[pin] = value

    def cleanup(self, pin: int) -> None:
        self.cleaned.append(pin)


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


def test_logging_button_treats_16s_hold_as_short_press_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.haltech_two_point_mm as haltech

    fake_gpio = FakeGPIO()
    haltech.GPIO = fake_gpio

    current_time = 0.0

    def fake_monotonic() -> float:
        return current_time

    monkeypatch.setattr(haltech.time, "monotonic", fake_monotonic)

    button = haltech.LoggingButton(gpio_pin=5, debounce_ms=120)
    current_time = 0.2
    fake_gpio.inputs[5] = fake_gpio.LOW
    assert button.consume_event() is None

    current_time = 1.8
    fake_gpio.inputs[5] = fake_gpio.HIGH
    assert button.consume_event() == "short_press"


def test_logging_button_press_event_is_detected(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.haltech_two_point_mm as haltech

    fake_gpio = FakeGPIO()
    haltech.GPIO = fake_gpio

    current_time = 0.0

    def fake_monotonic() -> float:
        return current_time

    monkeypatch.setattr(haltech.time, "monotonic", fake_monotonic)

    button = haltech.LoggingButton(gpio_pin=5, debounce_ms=120)
    current_time = 0.3
    fake_gpio.inputs[5] = fake_gpio.LOW
    assert button.consume_press_event() is False

    current_time = 0.35
    fake_gpio.inputs[5] = fake_gpio.HIGH
    assert button.consume_press_event() is True
