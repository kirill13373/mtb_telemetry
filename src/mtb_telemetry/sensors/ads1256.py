from __future__ import annotations

from collections.abc import Sequence
import time

import spidev


class ADS1256:
    """Minimal ADS1256 SPI driver.

    The ADS1256 itself does not expose a separate, user-facing chip identifier
    register in the same way as some other ICs. The practical and reliable
    hardware check is therefore the status register query via the SPI register
    read command.
    """

    STATUS_REGISTER_ADDRESS = 0x00
    MUX_REGISTER_ADDRESS = 0x01
    ADCON_REGISTER_ADDRESS = 0x02
    DRATE_REGISTER_ADDRESS = 0x03
    COMMAND_RESET = 0xFE
    COMMAND_SYNC = 0xFC
    COMMAND_STANDBY = 0xFD
    COMMAND_WAKEUP = 0xFF
    COMMAND_RDATA = 0x01
    COMMAND_RDATAC = 0x03
    COMMAND_SDATAC = 0x0F
    COMMAND_RREG = 0x10
    COMMAND_WREG = 0x50
    DRATE_1000_SPS = 0xA1
    DRATE_2000_SPS = 0xB0

    def __init__(self, bus: int = 0, device: int = 0) -> None:
        self.spi = spidev.SpiDev()
        self.bus = bus
        self.device = device
        self._selected_channel: int | None = None

    def open(self) -> None:
        self.spi.open(self.bus, self.device)

        # ADS1256 supports up to around 2 MHz SPI.
        # Start conservatively at 1 MHz for stable communication.
        self.spi.max_speed_hz = 1_000_000

        # SPI mode 1 according to the datasheet.
        self.spi.mode = 0b01

    def close(self) -> None:
        self.spi.close()

    def transfer(self, data: Sequence[int]) -> list[int]:
        """Send a command sequence over SPI and return the raw response bytes."""
        return list(self.spi.xfer2(list(data)))

    def write_register(self, register_address: int, values: Sequence[int]) -> list[int]:
        """Write one or more ADC registers through the SPI register write command."""
        if not 0 <= register_address <= 0x17:
            raise ValueError("ADS1256 register address must be in the valid range 0x00-0x17.")
        if len(values) < 1:
            raise ValueError("values must contain at least one byte.")

        frame = [self.COMMAND_WREG | register_address, len(values) - 1, *list(values)]
        return self.transfer(frame)

    def reset(self) -> list[int]:
        """Issue the ADS1256 reset command."""
        return self.transfer([self.COMMAND_RESET])

    def sync(self) -> list[int]:
        """Issue the ADS1256 sync command."""
        return self.transfer([self.COMMAND_SYNC])

    def standby(self) -> list[int]:
        """Enter standby mode with the ADS1256 standby command."""
        return self.transfer([self.COMMAND_STANDBY])

    def wake_up(self) -> list[int]:
        """Wake the ADS1256 from standby mode."""
        return self.transfer([self.COMMAND_WAKEUP])

    def stop_continuous_read(self) -> list[int]:
        """Stop continuous data mode so register access is deterministic."""
        return self.transfer([self.COMMAND_SDATAC])

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

        # ADS1256 RREG frame: [0x10 | addr, count-1], then read bytes.
        self.transfer([self.COMMAND_RREG | register_address, byte_count - 1])
        return self.transfer([0xFF] * byte_count)

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
        # A hard reset plus short settle helps avoid bad first reads on cold start.
        self.reset()
        time.sleep(0.05)
        self.stop_continuous_read()
        # STATUS: auto-calibration ON, optional buffer, MSB-first.
        # BUF=1 can reduce usable near-rail input range on single-supply setups.
        status_value = 0x06 if enable_input_buffer else 0x04
        self.write_register(self.STATUS_REGISTER_ADDRESS, [status_value])
        # ADCON: clock out off, sensor detect off, PGA=1.
        self.write_register(self.ADCON_REGISTER_ADDRESS, [0x00])
        # DRATE: 2000 SPS gives a fresh conversion every 0.5 ms.
        # At a 500 Hz read rate (2 ms loop) this ensures a new sample is always
        # ready and removes the need for a fixed pacing sleep inside read_adc_raw.
        self.write_register(self.DRATE_REGISTER_ADDRESS, [self.DRATE_2000_SPS])
        # Allow auto-calibration/filter to settle before first channel reads.
        time.sleep(0.05)
        self._selected_channel = None

    def select_single_ended_channel(self, channel: int) -> None:
        """Select a single-ended channel (AINx vs AINCOM)."""
        if not 0 <= channel <= 7:
            raise ValueError("channel must be between 0 and 7.")
        mux_value = (channel << 4) | 0x08
        self.write_register(self.MUX_REGISTER_ADDRESS, [mux_value])

    def read_adc_raw(self, channel: int = 0) -> int:
        """Read one 24-bit signed conversion from the selected single-ended channel."""
        if self._selected_channel != channel:
            self.select_single_ended_channel(channel)
            self.sync()
            self.wake_up()
            # Allow the digital filter to settle after MUX change.
            time.sleep(0.003)
            self._selected_channel = channel
            # Discard first conversion after channel switch.
            self.transfer([self.COMMAND_RDATA])
            time.sleep(0.00005)
            self.transfer([0xFF, 0xFF, 0xFF])

        # No pacing sleep here: the outer loop (target_period_s) handles the
        # 2 ms inter-sample cadence.  At 2000 SPS the ADC produces a fresh
        # conversion every 0.5 ms, so a new result is always ready by the time
        # we issue RDATA.

        # ADS1256 RDATA is a two-step transaction:
        # 1) Send RDATA command
        # 2) Clock out 24-bit result
        self.transfer([self.COMMAND_RDATA])
        time.sleep(0.00005)
        response = self.transfer([0xFF, 0xFF, 0xFF])
        raw = (response[0] << 16) | (response[1] << 8) | response[2]
        if raw & 0x800000:
            raw -= 1 << 24
        return raw

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