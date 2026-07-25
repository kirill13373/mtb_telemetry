"""Quick hardware check for ADS1256 status and chip-id nibble."""

from __future__ import annotations

from mtb_telemetry.sensors.ads1256 import ADS1256


def main() -> None:
    """Run a minimal live SPI check and print status/id values."""
    adc = ADS1256()
    adc.open()

    try:
        status_raw = adc.read_status()
        status_byte = adc.read_status_byte()
        chip_id_nibble = adc.read_chip_id()

        print("SPI geöffnet")
        print(f"status_raw: {status_raw}")
        print(f"status_byte: {status_byte} (0x{status_byte:02X})")
        print(f"chip_id_nibble: {chip_id_nibble} (0x{chip_id_nibble:X})")
    finally:
        adc.close()


if __name__ == "__main__":
    main()
