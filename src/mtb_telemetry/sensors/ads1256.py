from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
import sys
import time

import spidev


def _load_gpio_module():
    """Load RPi.GPIO from the venv or Raspberry Pi system packages."""
    try:
        import RPi.GPIO as rpi_gpio

        return rpi_gpio
    except ImportError:
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


class ADS1256:
    """ADS1256 driver for the Waveshare High-Precision AD/DA HAT.

    The HAT uses dedicated GPIOs for DRDY, RESET, PDWN and chip select. GPIO22
    is the real ADS1256 chip select; the SPI controller's CE0 pin is not wired
    to the ADC chip-select input on this board.
    """

    STATUS_REGISTER_ADDRESS = 0x00
    MUX_REGISTER_ADDRESS = 0x01
    ADCON_REGISTER_ADDRESS = 0x02
    DRATE_REGISTER_ADDRESS = 0x03
    COMMAND_RESET = 0xFE
    COMMAND_SYNC = 0xFC
    COMMAND_STANDBY = 0xFD
    COMMAND_WAKEUP = 0x00
    COMMAND_RDATA = 0x01
    COMMAND_RDATAC = 0x03
    COMMAND_SDATAC = 0x0F
    COMMAND_RREG = 0x10
    COMMAND_WREG = 0x50
    DRATE_1000_SPS = 0xA1
    DRATE_2000_SPS = 0xB0
    DRDY_GPIO = 17
    RESET_GPIO = 18
    PDWN_GPIO = 27
    CS_GPIO = 22
    T6_DELAY_S = 0.000010
    COMMAND_DELAY_S = 0.000005

    def __init__(self, bus: int = 0, device: int = 0) -> None:
        self.spi = spidev.SpiDev()
        self.bus = bus
        self.device = device
        self._selected_channel: int | None = None
        self._gpio_initialized = False

    def open(self) -> None:
        if GPIO is None:
            raise RuntimeError(
                "RPi.GPIO is not available. Install python3-rpi.gpio or run on Raspberry Pi."
            )

        self.spi.open(self.bus, self.device)

        # ADS1256 supports up to around 2 MHz SPI.
        # Start conservatively at 1 MHz for stable communication.
        self.spi.max_speed_hz = 1_000_000

        # SPI mode 1 according to the datasheet.
        self.spi.mode = 0b01
        # Waveshare routes ADS1256 CS to BCM GPIO22, not SPI CE0 (BCM GPIO8).
        self.spi.no_cs = True

        GPIO.setwarnings(False)
        GPIO.setmode(GPIO.BCM)
        GPIO.setup(self.CS_GPIO, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.RESET_GPIO, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.PDWN_GPIO, GPIO.OUT, initial=GPIO.HIGH)
        GPIO.setup(self.DRDY_GPIO, GPIO.IN)
        self._gpio_initialized = True

    def close(self) -> None:
        if self._gpio_initialized:
            GPIO.output(self.CS_GPIO, GPIO.HIGH)
            GPIO.output(self.PDWN_GPIO, GPIO.HIGH)
            GPIO.cleanup(
                [self.CS_GPIO, self.RESET_GPIO, self.PDWN_GPIO, self.DRDY_GPIO]
            )
            self._gpio_initialized = False
        self.spi.close()

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Perform a raw SPI transfer without changing the manual chip select."""
        return list(self.spi.xfer2(list(data)))

    def _select(self) -> None:
        GPIO.output(self.CS_GPIO, GPIO.LOW)

    def _deselect(self) -> None:
        GPIO.output(self.CS_GPIO, GPIO.HIGH)

    def _write_command(self, command: int) -> list[int]:
        self._select()
        try:
            return self.transfer([command])
        finally:
            self._deselect()

    def wait_drdy(self, timeout_s: float = 1.0) -> None:
        """Wait until the ADS1256 signals a completed conversion."""
        deadline = time.monotonic() + timeout_s
        while GPIO.input(self.DRDY_GPIO) != GPIO.LOW:
            if time.monotonic() >= deadline:
                raise TimeoutError(
                    f"ADS1256 DRDY timeout on BCM GPIO {self.DRDY_GPIO}. "
                    "Check RESET/PDWN, board seating and the Waveshare pin mapping."
                )

    def hardware_reset(self) -> None:
        """Reset the ADS1256 through the Waveshare HAT RESET line."""
        GPIO.output(self.PDWN_GPIO, GPIO.HIGH)
        GPIO.output(self.RESET_GPIO, GPIO.HIGH)
        time.sleep(0.2)
        GPIO.output(self.RESET_GPIO, GPIO.LOW)
        time.sleep(0.2)
        GPIO.output(self.RESET_GPIO, GPIO.HIGH)
        time.sleep(0.2)
        self._selected_channel = None
        self.wait_drdy()

    def write_register(self, register_address: int, values: Sequence[int]) -> list[int]:
        """Write one or more ADC registers through the SPI register write command."""
        if not 0 <= register_address <= 0x17:
            raise ValueError("ADS1256 register address must be in the valid range 0x00-0x17.")
        if len(values) < 1:
            raise ValueError("values must contain at least one byte.")

        frame = [self.COMMAND_WREG | register_address, len(values) - 1, *list(values)]
        self._select()
        try:
            return self.transfer(frame)
        finally:
            self._deselect()

    def reset(self) -> list[int]:
        """Issue the ADS1256 reset command."""
        return self._write_command(self.COMMAND_RESET)

    def sync(self) -> list[int]:
        """Issue the ADS1256 sync command."""
        result = self._write_command(self.COMMAND_SYNC)
        time.sleep(self.COMMAND_DELAY_S)
        return result

    def standby(self) -> list[int]:
        """Enter standby mode with the ADS1256 standby command."""
        return self._write_command(self.COMMAND_STANDBY)

    def wake_up(self) -> list[int]:
        """Wake the ADS1256 from standby mode."""
        result = self._write_command(self.COMMAND_WAKEUP)
        time.sleep(self.COMMAND_DELAY_S)
        return result

    def stop_continuous_read(self) -> list[int]:
        """Stop continuous data mode so register access is deterministic."""
        result = self._write_command(self.COMMAND_SDATAC)
        time.sleep(self.COMMAND_DELAY_S)
        return result

    def read_register(self, register_address: int, byte_count: int = 1) -> list[int]:
        """Read one or more ADC registers through the SPI register read command.

        Args:
            register_address: ADS1256 register address to read.
            byte_count: Number of bytes to read from the register block.

        Returns:
            Raw register bytes returned by the device.
        """
        if not 0 <= register_address <= 0x17:
            raise ValueError("ADS1256 register address must be in the valid range 0x00-0x17.")
        if byte_count < 1:
            raise ValueError("byte_count must be at least 1.")

        self.wait_drdy()
        self._select()
        try:
            self.transfer([self.COMMAND_RREG | register_address, byte_count - 1])
            # ADS1256 t6 requires idle time without SCLK after RREG.
            time.sleep(self.T6_DELAY_S)
            return self.transfer([0xFF] * byte_count)
        finally:
            self._deselect()

    def read_status(self) -> list[int]:
        """Read the ADS1256 status register.

        This is the most reliable hardware-level identification query available
        from the device itself, because the ADS1256 does not provide a dedicated
        chip-ID register in the same format as some other converters.
        """
        return self.read_register(self.STATUS_REGISTER_ADDRESS, byte_count=1)

    def read_status_byte(self) -> int:
        """Read and return the ADS1256 status register as a single byte."""
        return self.read_status()[0]

    def read_chip_id(self) -> int:
        """Extract the ADS1256 device nibble from the status register.

        The identifier is encoded in the upper nibble of the status byte.
        """
        return (self.read_status_byte() >> 4) & 0x0F

    def initialize_single_ended(self, enable_input_buffer: bool = False) -> None:
        """Initialize a conservative single-ended configuration for quick testing.

        Args:
            enable_input_buffer: Enable ADS1256 analog input buffer.
                Keep this disabled for widest 0-5V single-ended range.
        """
        self.hardware_reset()
        chip_id = self.read_chip_id()
        if chip_id != 0x03:
            raise RuntimeError(
                f"ADS1256 chip ID mismatch: expected 0x3, got 0x{chip_id:X}. "
                "Check Waveshare CS=GPIO22, DRDY=GPIO17, RESET=GPIO18 and PDWN=GPIO27."
            )

        self.stop_continuous_read()
        # STATUS: auto-calibration ON, optional buffer, MSB-first.
        # BUF=1 can reduce usable near-rail input range on single-supply setups.
        status_value = 0x06 if enable_input_buffer else 0x04
        # Configure STATUS, MUX, ADCON and DRATE in one WREG transaction. This
        # triggers auto-calibration only once and matches the Waveshare board.
        self.write_register(
            self.STATUS_REGISTER_ADDRESS,
            [status_value, 0x08, 0x00, self.DRATE_2000_SPS],
        )
        self.wait_drdy()
        self._selected_channel = None

    def select_single_ended_channel(self, channel: int) -> None:
        """Select a single-ended channel (AINx vs AINCOM)."""
        if not 0 <= channel <= 7:
            raise ValueError("channel must be between 0 and 7.")
        self.wait_drdy()
        mux_value = (channel << 4) | 0x08
        self.write_register(self.MUX_REGISTER_ADDRESS, [mux_value])

    def read_adc_raw(self, channel: int = 0) -> int:
        """Read one 24-bit signed conversion from the selected single-ended channel."""
        if self._selected_channel != channel:
            self.select_single_ended_channel(channel)
            self.sync()
            self.wake_up()
            self._selected_channel = channel
            # Discard the first completed conversion after a MUX change.
            self.wait_drdy()
            self._read_current_conversion()

        self.wait_drdy()
        response = self._read_current_conversion()
        raw = (response[0] << 16) | (response[1] << 8) | response[2]
        if raw & 0x800000:
            raw -= 1 << 24
        return raw

    def _read_current_conversion(self) -> list[int]:
        """Read one completed conversion while manually holding CS active."""
        self._select()
        try:
            self.transfer([self.COMMAND_RDATA])
            # ADS1256 t6 requires idle time without SCLK after RDATA.
            time.sleep(self.T6_DELAY_S)
            return self.transfer([0xFF, 0xFF, 0xFF])
        finally:
            self._deselect()

    def read_adc_raw_stable(self, channel: int = 0, samples: int = 5) -> int:
        """Read multiple conversions and return the median for better stability."""
        if samples < 1:
            raise ValueError("samples must be at least 1.")

        values = [self.read_adc_raw(channel=channel) for _ in range(samples)]
        values.sort()
        return values[len(values) // 2]

    def prime_channel(self, channel: int = 0, discard: int = 8) -> None:
        """Prime a channel by discarding initial conversions after startup.

        This reduces startup transients in quick bench tests.
        """
        if discard < 0:
            raise ValueError("discard must be non-negative.")
        for _ in range(discard):
            self.read_adc_raw(channel=channel)

    def raw_to_voltage(self, raw_value: int, vref: float = 5.0, pga: int = 1) -> float:
        """Convert signed 24-bit ADC code to input voltage."""
        full_scale = (1 << 23) - 1
        return (raw_value / full_scale) * (vref / pga)