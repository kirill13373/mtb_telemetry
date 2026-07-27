#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/pi/mtb_telemetry"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

BUTTON_GPIO="${BUTTON_GPIO:-27}"
BUTTON_DEBOUNCE_MS="${BUTTON_DEBOUNCE_MS:-120}"
TARGET_HZ="${TARGET_HZ:-80}"
PRINT_EVERY="${PRINT_EVERY:-1}"

cd "$PROJECT_DIR"

exec "$PYTHON_BIN" scripts/haltech_two_point_mm.py \
  --button-gpio "$BUTTON_GPIO" \
  --button-debounce-ms "$BUTTON_DEBOUNCE_MS" \
  --target-hz "$TARGET_HZ" \
  --quiet \
  --print-every "$PRINT_EVERY"
