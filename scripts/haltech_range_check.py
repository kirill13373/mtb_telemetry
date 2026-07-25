"""Live range diagnostic for Haltech sensor on ADS1256 AD0.

This script helps determine whether the signal plateau is caused by ADC clipping
or by the sensor/mechanical setup not using the full electrical range.
"""

from __future__ import annotations

import time

from mtb_telemetry.sensors.ads1256 import ADS1256


ADC_MAX = (1 << 23) - 1


def main() -> None:
    """Stream AD0 values and keep track of observed min/max range."""
    adc = ADS1256()
    adc.open()

    min_raw: int | None = None
    max_raw: int | None = None

    try:
        adc.initialize_single_ended()
        adc.prime_channel(channel=0, discard=10)
        print("Move the suspension slowly through full travel. Stop with Ctrl+C.")

        while True:
            raw = adc.read_adc_raw_stable(channel=0, samples=9)
            voltage = adc.raw_to_voltage(raw, vref=5.0, pga=1)

            if min_raw is None or raw < min_raw:
                min_raw = raw
            if max_raw is None or raw > max_raw:
                max_raw = raw

            min_v = adc.raw_to_voltage(min_raw, vref=5.0, pga=1)
            max_v = adc.raw_to_voltage(max_raw, vref=5.0, pga=1)
            span_v = max_v - min_v
            clip_note = " [ADC_CLIP]" if raw >= ADC_MAX else ""

            print(
                f"now={voltage:>6.3f} V  "
                f"min={min_v:>6.3f} V  "
                f"max={max_v:>6.3f} V  "
                f"span={span_v:>6.3f} V{clip_note}"
            )
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nRange check stopped.")
        if min_raw is not None and max_raw is not None:
            min_v = adc.raw_to_voltage(min_raw, vref=5.0, pga=1)
            max_v = adc.raw_to_voltage(max_raw, vref=5.0, pga=1)
            span_v = max_v - min_v
            print("Summary:")
            print(f"  min_raw={min_raw}, min_v={min_v:.4f} V")
            print(f"  max_raw={max_raw}, max_v={max_v:.4f} V")
            print(f"  span_v={span_v:.4f} V")
            if max_raw >= ADC_MAX:
                print("  Result: ADC clipping detected (electrical full-scale reached).")
            else:
                print("  Result: no ADC clipping, likely sensor/mechanical range limit.")
    finally:
        adc.close()


if __name__ == "__main__":
    main()
