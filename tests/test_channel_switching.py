from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def load_module():
    spec = importlib.util.spec_from_file_location(
        "haltech_two_point_mm_test",
        PROJECT_ROOT / "scripts" / "haltech_two_point_mm.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_fast_channel_switching_is_disabled_by_default():
    module = load_module()
    assert module.resolve_channel_switching_mode(target_hz=500.0, adc_samples=1, fast_channel_switching=False) is False


def test_fast_channel_switching_can_be_enabled_explicitly():
    module = load_module()
    assert module.resolve_channel_switching_mode(target_hz=500.0, adc_samples=1, fast_channel_switching=True) is True
