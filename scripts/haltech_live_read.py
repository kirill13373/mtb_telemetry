"""Live AD0 readout for first Haltech sensor bring-up.

This script prints raw ADC values and converted volts continuously so the
sensor response is visible immediately while moving the suspension.
"""

from __future__ import annotations

import time

from mtb_telemetry.sensors.ads1256 import ADS1256


def main() -> None:
    """Run a live read loop on ADS1256 channel AD0."""
    adc = ADS1256()
    adc.open()

    try:
        adc.initialize_single_ended()
        adc.prime_channel(channel=0, discard=10)
        print("ADS1256 live read started on AD0. Stop with Ctrl+C.")

        while True:
            raw = adc.read_adc_raw_stable(channel=0, samples=7)
            voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)
            clip_note = " [CLIP]" if raw >= ((1 << 23) - 1) else ""
            print(f"raw={raw:>9d}  voltage={voltage:>7.4f} V{clip_note}")
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nLive read stopped.")
    finally:
        adc.close()


if __name__ == "__main__":
    main()
