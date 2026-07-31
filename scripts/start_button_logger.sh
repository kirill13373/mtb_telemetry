#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/pi/mtb_telemetry"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

CONTROL_MODE="${CONTROL_MODE:-switch}"
CONTROL_GPIO="${CONTROL_GPIO:-27}"
CONTROL_DEBOUNCE_MS="${CONTROL_DEBOUNCE_MS:-120}"
SHUTDOWN_GPIO="${SHUTDOWN_GPIO:-}"
SHUTDOWN_DEBOUNCE_MS="${SHUTDOWN_DEBOUNCE_MS:-800}"
TARGET_HZ="${TARGET_HZ:-500}"
ADC_SAMPLES="${ADC_SAMPLES:-1}"
CSV_FLUSH_EVERY="${CSV_FLUSH_EVERY:-200}"
PRINT_EVERY="${PRINT_EVERY:-1}"

cd "$PROJECT_DIR"

common_args=(
  --target-hz "$TARGET_HZ"
  --adc-samples "$ADC_SAMPLES"
  --csv-flush-every "$CSV_FLUSH_EVERY"
  --quiet
  --print-every "$PRINT_EVERY"
)

if [[ -n "$SHUTDOWN_GPIO" ]]; then
  common_args+=(
    --shutdown-button-gpio "$SHUTDOWN_GPIO"
    --shutdown-button-debounce-ms "$SHUTDOWN_DEBOUNCE_MS"
  )
fi

if [[ "$CONTROL_MODE" == "switch" ]]; then
  exec "$PYTHON_BIN" scripts/haltech_two_point_mm.py \
    --switch-gpio "$CONTROL_GPIO" \
    --switch-debounce-ms "$CONTROL_DEBOUNCE_MS" \
    "${common_args[@]}"
elif [[ "$CONTROL_MODE" == "button" ]]; then
  exec "$PYTHON_BIN" scripts/haltech_two_point_mm.py \
    --button-gpio "$CONTROL_GPIO" \
    --button-debounce-ms "$CONTROL_DEBOUNCE_MS" \
    "${common_args[@]}"
else
  echo "Unsupported CONTROL_MODE='$CONTROL_MODE' (expected 'switch' or 'button')" >&2
  exit 2
fi
