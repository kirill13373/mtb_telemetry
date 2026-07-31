"""Quick hardware check for the Waveshare ADS1256 HAT."""

from __future__ import annotations

from mtb_telemetry.sensors.ads1256 import ADS1256


def main() -> None:
    """Initialize the HAT and print status, chip ID and an AD0 sample."""
    adc = ADS1256()
    adc.open()

    try:
        adc.initialize_single_ended(enable_input_buffer=False)
        status_raw = adc.read_status()
        status_byte = status_raw[0]
        chip_id_nibble = (status_byte >> 4) & 0x0F
        raw = adc.read_adc_raw(channel=0)
        voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)

        print("Waveshare ADS1256 initialized")
        print("Pins: DRDY=BCM17 RESET=BCM18 PDWN=BCM27 CS=BCM22")
        print(f"status_raw: {status_raw}")
        print(f"status_byte: {status_byte} (0x{status_byte:02X})")
        print(f"chip_id_nibble: {chip_id_nibble} (0x{chip_id_nibble:X})")
        print(f"AD0 raw: {raw}")
        print(f"AD0 voltage: {voltage:.6f} V")

        if chip_id_nibble != 0x03:
            raise RuntimeError(
                f"ADS1256 check failed: expected chip ID 0x3, got 0x{chip_id_nibble:X}"
            )
    finally:
        adc.close()


if __name__ == "__main__":
    main()
