"""Tests for the ADS1256 driver package import and hardware access."""

from __future__ import annotations

import os

import pytest

from mtb_telemetry.sensors.ads1256 import ADS1256


SPI_DEVICE_PRESENT = os.path.exists("/dev/spidev0.0")


def test_ads1256_can_be_instantiated() -> None:
    """The ADS1256 driver should be importable from the installed package.

    This test remains hardware-safe because it only verifies object creation and
    the expected configuration defaults.
    """
    adc = ADS1256()

    assert adc.bus == 0
    assert adc.device == 0
    assert adc.spi is not None


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
        status = adc.read_status()
        chip_id = adc.read_chip_id()
    finally:
        adc.close()

    assert isinstance(status, list)
    assert isinstance(chip_id, list)
    assert len(status) >= 1
    assert len(chip_id) >= 1