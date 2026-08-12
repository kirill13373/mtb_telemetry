from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"


def load_script_module():
    if str(SRC_ROOT) not in sys.path:
        sys.path.insert(0, str(SRC_ROOT))

    spec = importlib.util.spec_from_file_location(
        "haltech_two_point_mm_test",
        PROJECT_ROOT / "scripts" / "haltech_two_point_mm.py",
    )
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_calibration_and_log_paths_resolve_from_project_root():
    module = load_script_module()

    assert module.PROJECT_ROOT == PROJECT_ROOT
    assert module.CALIBRATION_FILE_SHOCK == PROJECT_ROOT / "calibration" / "haltech_ads1256_ad0.json"
    assert module.CALIBRATION_FILE_FORK == PROJECT_ROOT / "calibration" / "haltech_ads1256_ad1.json"
    assert module.LOG_DIR == PROJECT_ROOT / "data"
    assert module.SUFNI_DIR == PROJECT_ROOT / "data" / "sufni"
