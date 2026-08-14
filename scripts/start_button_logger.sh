#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/pi/mtb_telemetry"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

CONTROL_MODE="${CONTROL_MODE:-switch}"
CONTROL_GPIO="${CONTROL_GPIO:-27}"
CONTROL_DEBOUNCE_MS="${CONTROL_DEBOUNCE_MS:-120}"
CONTROL_LONG_PRESS_MS="${CONTROL_LONG_PRESS_MS:-2500}"
SHUTDOWN_GPIO="${SHUTDOWN_GPIO:-}"
SHUTDOWN_DEBOUNCE_MS="${SHUTDOWN_DEBOUNCE_MS:-800}"
STATUS_LED_GPIO="${STATUS_LED_GPIO:-}"
STATUS_LED_ACTIVE_LOW="${STATUS_LED_ACTIVE_LOW:-0}"
SESSION_METRICS_JSON="${SESSION_METRICS_JSON:-}"
TARGET_HZ="${TARGET_HZ:-500}"
ADC_SAMPLES="${ADC_SAMPLES:-1}"
SHOCK_SENSOR_TRAVEL_MM_MAX="${SHOCK_SENSOR_TRAVEL_MM_MAX:-100}"
FORK_SENSOR_TRAVEL_MM_MAX="${FORK_SENSOR_TRAVEL_MM_MAX:-200}"
SHOCK_BIKE_TRAVEL_MM="${SHOCK_BIKE_TRAVEL_MM:-60}"
FORK_BIKE_TRAVEL_MM="${FORK_BIKE_TRAVEL_MM:-170}"
BINARY_BLOCK_RECORDS="${BINARY_BLOCK_RECORDS:-256}"
WRITER_QUEUE_BLOCKS="${WRITER_QUEUE_BLOCKS:-16}"
WRITER_FSYNC_INTERVAL_S="${WRITER_FSYNC_INTERVAL_S:-2.0}"
PRODUCER_CPU="${PRODUCER_CPU:-}"
WRITER_CPU="${WRITER_CPU:-}"
OLED_ENABLE="${OLED_ENABLE:-1}"
OLED_I2C_BUS="${OLED_I2C_BUS:-1}"
OLED_I2C_ADDRESS="${OLED_I2C_ADDRESS:-0x3C}"
OLED_REFRESH_HZ="${OLED_REFRESH_HZ:-2.0}"
PRINT_EVERY="${PRINT_EVERY:-1}"

cd "$PROJECT_DIR"

echo "Starting MTB telemetry logger..." >&2
echo "CONTROL_MODE='${CONTROL_MODE}' CONTROL_GPIO='${CONTROL_GPIO}' CONTROL_DEBOUNCE_MS='${CONTROL_DEBOUNCE_MS}' CONTROL_LONG_PRESS_MS='${CONTROL_LONG_PRESS_MS}'" >&2
echo "SHUTDOWN_GPIO='${SHUTDOWN_GPIO}' SHUTDOWN_DEBOUNCE_MS='${SHUTDOWN_DEBOUNCE_MS}'" >&2
echo "STATUS_LED_GPIO='${STATUS_LED_GPIO}' STATUS_LED_ACTIVE_LOW='${STATUS_LED_ACTIVE_LOW}'" >&2
echo "SESSION_METRICS_JSON='${SESSION_METRICS_JSON}'" >&2
echo "TARGET_HZ='${TARGET_HZ}' ADC_SAMPLES='${ADC_SAMPLES}' SHOCK_SENSOR_TRAVEL_MM_MAX='${SHOCK_SENSOR_TRAVEL_MM_MAX}' FORK_SENSOR_TRAVEL_MM_MAX='${FORK_SENSOR_TRAVEL_MM_MAX}' SHOCK_BIKE_TRAVEL_MM='${SHOCK_BIKE_TRAVEL_MM}' FORK_BIKE_TRAVEL_MM='${FORK_BIKE_TRAVEL_MM}' PRINT_EVERY='${PRINT_EVERY}'" >&2
echo "BINARY_BLOCK_RECORDS='${BINARY_BLOCK_RECORDS}' WRITER_QUEUE_BLOCKS='${WRITER_QUEUE_BLOCKS}' WRITER_FSYNC_INTERVAL_S='${WRITER_FSYNC_INTERVAL_S}'" >&2
echo "PRODUCER_CPU='${PRODUCER_CPU}' WRITER_CPU='${WRITER_CPU}'" >&2
echo "OLED_ENABLE='${OLED_ENABLE}' OLED_I2C_BUS='${OLED_I2C_BUS}' OLED_I2C_ADDRESS='${OLED_I2C_ADDRESS}' OLED_REFRESH_HZ='${OLED_REFRESH_HZ}'" >&2

common_args=(
  --target-hz "$TARGET_HZ"
  --adc-samples "$ADC_SAMPLES"
  --shock-travel-mm-max "$SHOCK_SENSOR_TRAVEL_MM_MAX"
  --fork-travel-mm-max "$FORK_SENSOR_TRAVEL_MM_MAX"
  --shock-bike-travel-mm "$SHOCK_BIKE_TRAVEL_MM"
  --fork-bike-travel-mm "$FORK_BIKE_TRAVEL_MM"
  --binary-block-records "$BINARY_BLOCK_RECORDS"
  --writer-queue-blocks "$WRITER_QUEUE_BLOCKS"
  --writer-fsync-interval-s "$WRITER_FSYNC_INTERVAL_S"
  --quiet
  --print-every "$PRINT_EVERY"
)

if [[ -n "$PRODUCER_CPU" ]]; then
  common_args+=(--producer-cpu "$PRODUCER_CPU")
fi

if [[ -n "$WRITER_CPU" ]]; then
  common_args+=(--writer-cpu "$WRITER_CPU")
fi

if [[ "$OLED_ENABLE" == "1" ]]; then
  common_args+=(
    --oled-display
    --oled-i2c-bus "$OLED_I2C_BUS"
    --oled-i2c-address "$OLED_I2C_ADDRESS"
    --oled-refresh-hz "$OLED_REFRESH_HZ"
  )
fi

if [[ -n "$SHUTDOWN_GPIO" ]]; then
  common_args+=(
    --shutdown-button-gpio "$SHUTDOWN_GPIO"
    --shutdown-button-debounce-ms "$SHUTDOWN_DEBOUNCE_MS"
  )
fi

if [[ -n "$STATUS_LED_GPIO" ]]; then
  common_args+=(--status-led-gpio "$STATUS_LED_GPIO")
  if [[ "$STATUS_LED_ACTIVE_LOW" == "1" ]]; then
    common_args+=(--status-led-active-low)
  fi
fi

if [[ -n "$SESSION_METRICS_JSON" ]]; then
  common_args+=(--session-metrics-json "$SESSION_METRICS_JSON")
fi

if [[ "$CONTROL_MODE" == "switch" ]]; then
  echo "Exec: $PYTHON_BIN scripts/haltech_two_point_mm.py --switch-gpio $CONTROL_GPIO --switch-debounce-ms $CONTROL_DEBOUNCE_MS ${common_args[*]}" >&2
  exec "$PYTHON_BIN" scripts/haltech_two_point_mm.py \
    --switch-gpio "$CONTROL_GPIO" \
    --switch-debounce-ms "$CONTROL_DEBOUNCE_MS" \
    "${common_args[@]}"
elif [[ "$CONTROL_MODE" == "button" ]]; then
  echo "Exec: $PYTHON_BIN scripts/haltech_two_point_mm.py --button-gpio $CONTROL_GPIO --button-debounce-ms $CONTROL_DEBOUNCE_MS --button-long-press-ms $CONTROL_LONG_PRESS_MS ${common_args[*]}" >&2
  exec "$PYTHON_BIN" scripts/haltech_two_point_mm.py \
    --button-gpio "$CONTROL_GPIO" \
    --button-debounce-ms "$CONTROL_DEBOUNCE_MS" \
    --button-long-press-ms "$CONTROL_LONG_PRESS_MS" \
    "${common_args[@]}"
else
  echo "Unsupported CONTROL_MODE='$CONTROL_MODE' (expected 'switch' or 'button')" >&2
  exit 2
fi
