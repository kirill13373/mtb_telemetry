from __future__ import annotations

from collections.abc import Sequence

import spidev


class ADS1256:
    """Minimal ADS1256 SPI driver.

    The ADS1256 itself does not expose a separate, user-facing chip identifier
    register in the same way as some other ICs. The practical and reliable
    hardware check is therefore the status register query via the SPI register
    read command.
    """

    STATUS_REGISTER_ADDRESS = 0x00
    COMMAND_RESET = 0xFE
    COMMAND_SYNC = 0xFC
    COMMAND_STANDBY = 0xFD
    COMMAND_WAKEUP = 0xFF
    COMMAND_RDATA = 0x01
    COMMAND_RDATAC = 0x03
    COMMAND_SDATAC = 0x0F
    COMMAND_RREG = 0x20
    COMMAND_WREG = 0x40

    def __init__(self, bus: int = 0, device: int = 0) -> None:
        self.spi = spidev.SpiDev()
        self.bus = bus
        self.device = device

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

        self.transfer([self.COMMAND_RREG, register_address, byte_count - 1])
        return self.transfer([0xFF] * byte_count)

    def read_status(self) -> list[int]:
        """Read the ADS1256 status register.

        This is the most reliable hardware-level identification query available
        from the device itself, because the ADS1256 does not provide a dedicated
        chip-ID register in the same format as some other converters.
        """
        return self.read_register(self.STATUS_REGISTER_ADDRESS, byte_count=1)

    def read_chip_id(self) -> list[int]:
        """Return the raw status-byte response as the practical chip ID probe.

        The ADS1256 exposes status information through the register interface, not
        a separate chip identifier register. The returned value is therefore the
        most direct hardware-level identifier the driver can read from the ADC.
        """
        return self.read_status()