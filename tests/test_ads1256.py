"""Tests for the ADS1256 driver package import and hardware access."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest

try:
    import spidev  # noqa: F401
except ImportError:
    class HostSpiDevStub:
        """Import-only spidev stand-in for Windows test collection."""

        def open(self, bus: int, device: int) -> None:
            raise RuntimeError("Real SPI is unavailable on this host")

        def close(self) -> None:
            pass

    sys.modules["spidev"] = SimpleNamespace(SpiDev=HostSpiDevStub)

import mtb_telemetry.sensors.ads1256 as ads1256_module
from mtb_telemetry.sensors.ads1256 import ADS1256


SPI_DEVICE_PRESENT = os.path.exists("/dev/spidev0.0")


class FakeSpi:
    """Minimal spidev replacement for protocol-level unit tests."""

    def __init__(self) -> None:
        self.max_speed_hz = 0
        self.mode = 0
        self.no_cs = False
        self.opened: tuple[int, int] | None = None
        self.transfers: list[list[int]] = []

    def open(self, bus: int, device: int) -> None:
        self.opened = (bus, device)

    def close(self) -> None:
        self.opened = None

    def xfer2(self, data: list[int]) -> list[int]:
        self.transfers.append(list(data))
        if data == [0xFF]:
            return [0x30]
        return [0x00] * len(data)


class FakeGpio:
    """Small RPi.GPIO replacement that records pin configuration and levels."""

    BCM = 11
    IN = 1
    OUT = 0
    LOW = 0
    HIGH = 1

    def __init__(self) -> None:
        self.levels: dict[int, int] = {}
        self.setup_calls: list[tuple[int, int, int | None]] = []
        self.cleaned: list[int] = []

    def setwarnings(self, enabled: bool) -> None:
        pass

    def setmode(self, mode: int) -> None:
        assert mode == self.BCM

    def setup(self, pin: int, mode: int, initial: int | None = None) -> None:
        self.setup_calls.append((pin, mode, initial))
        if initial is not None:
            self.levels[pin] = initial
        elif mode == self.IN:
            self.levels.setdefault(pin, self.LOW)

    def output(self, pin: int, level: int) -> None:
        self.levels[pin] = level

    def input(self, pin: int) -> int:
        return self.levels.get(pin, self.LOW)

    def cleanup(self, pins: list[int] | int) -> None:
        self.cleaned.extend(pins if isinstance(pins, list) else [pins])


def build_fake_adc(monkeypatch: pytest.MonkeyPatch) -> tuple[ADS1256, FakeSpi, FakeGpio]:
    """Build an ADS1256 using fake SPI and GPIO dependencies."""
    fake_spi = FakeSpi()
    fake_gpio = FakeGpio()
    monkeypatch.setattr(ads1256_module.spidev, "SpiDev", lambda: fake_spi)
    monkeypatch.setattr(ads1256_module, "GPIO", fake_gpio)
    return ADS1256(), fake_spi, fake_gpio


def test_ads1256_can_be_instantiated() -> None:
    """The ADS1256 driver should be importable from the installed package.

    This test remains hardware-safe because it only verifies object creation and
    the expected configuration defaults.
    """
    adc = ADS1256()

    assert adc.bus == 0
    assert adc.device == 0
    assert adc.spi is not None


def test_waveshare_open_configures_reserved_gpio_pins(monkeypatch: pytest.MonkeyPatch) -> None:
    """Opening the HAT must reserve CS, RESET, PDWN and DRDY correctly."""
    adc, fake_spi, fake_gpio = build_fake_adc(monkeypatch)

    adc.open()

    assert fake_spi.opened == (0, 0)
    assert fake_spi.no_cs is True
    assert (ADS1256.CS_GPIO, fake_gpio.OUT, fake_gpio.HIGH) in fake_gpio.setup_calls
    assert (ADS1256.RESET_GPIO, fake_gpio.OUT, fake_gpio.HIGH) in fake_gpio.setup_calls
    assert (ADS1256.PDWN_GPIO, fake_gpio.OUT, fake_gpio.HIGH) in fake_gpio.setup_calls
    assert (ADS1256.DRDY_GPIO, fake_gpio.IN, None) in fake_gpio.setup_calls


def test_register_read_holds_manual_cs(monkeypatch: pytest.MonkeyPatch) -> None:
    """RREG command and payload read must run while Waveshare CS is active."""
    adc, fake_spi, fake_gpio = build_fake_adc(monkeypatch)
    adc.open()

    status = adc.read_status()

    assert status == [0x30]
    assert fake_spi.transfers[-2:] == [[ADS1256.COMMAND_RREG, 0x00], [0xFF]]
    assert fake_gpio.levels[ADS1256.CS_GPIO] == fake_gpio.HIGH


def test_wait_drdy_times_out_when_board_is_not_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stuck-high DRDY line must fail explicitly instead of returning zeros."""
    adc, _, fake_gpio = build_fake_adc(monkeypatch)
    adc.open()
    fake_gpio.levels[ADS1256.DRDY_GPIO] = fake_gpio.HIGH

    with pytest.raises(TimeoutError, match="DRDY timeout"):
        adc.wait_drdy(timeout_s=0.0)


def test_initialize_rejects_wrong_chip_id(monkeypatch: pytest.MonkeyPatch) -> None:
    """Initialization must stop when the ADS1256 is not responding."""
    adc, _, _ = build_fake_adc(monkeypatch)
    adc.open()
    monkeypatch.setattr(adc, "hardware_reset", lambda: None)
    monkeypatch.setattr(adc, "read_chip_id", lambda: 0x00)

    with pytest.raises(RuntimeError, match="chip ID mismatch"):
        adc.initialize_single_ended()


@pytest.mark.skipif(not SPI_DEVICE_PRESENT, reason="ADS1256 hardware test requires /dev/spidev0.0")
def test_ads1256_hardware_spi_transfer() -> None:
    """Open the real SPI connection and verify that the ADS1256 responds.

    The test is intentionally conservative: it only validates that an SPI
    transfer can be performed and that the response is a non-empty list.
    """
    adc = ADS1256()

    try:
        adc.open()
        response = adc.transfer([0xFF])
    finally:
        adc.close()

    assert isinstance(response, list)
    assert len(response) >= 1


@pytest.mark.skipif(not SPI_DEVICE_PRESENT, reason="ADS1256 hardware test requires /dev/spidev0.0")
def test_ads1256_status_query() -> None:
    """Read the ADS1256 status register over the real SPI interface.

    The ADS1256 does not expose a dedicated chip-ID register in the same way as
    some other ADCs, so the practical equivalent hardware probe is the status
    register readback.
    """
    adc = ADS1256()

    try:
        adc.open()
        adc.initialize_single_ended()
        status = adc.read_status()
        status_byte = adc.read_status_byte()
        chip_id = adc.read_chip_id()
    finally:
        adc.close()

    assert isinstance(status, list)
    assert len(status) >= 1
    assert isinstance(status_byte, int)
    assert 0 <= status_byte <= 0xFF
    assert chip_id == 0x03