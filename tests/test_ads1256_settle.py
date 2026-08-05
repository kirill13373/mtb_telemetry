from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from mtb_telemetry.sensors.ads1256 import ADS1256


def test_ads1256_channel_settle_can_be_configured():
    adc = ADS1256(channel_settle_s=0.00025)
    assert adc.channel_settle_s == 0.00025
