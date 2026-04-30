#!/usr/bin/env bash
# Sourced by every other script. Loads .env, exports MQTT_*, checks deps.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${ENV_FILE:-$SCRIPT_DIR/../.env}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "missing $ENV_FILE — copy .env.example and fill it in" >&2
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${MQTT_HOST:?MQTT_HOST not set in $ENV_FILE}"
: "${MQTT_PORT:=1883}"
: "${MQTT_USER:?MQTT_USER not set in $ENV_FILE}"
: "${MQTT_PASS:?MQTT_PASS not set in $ENV_FILE}"

if ! command -v mosquitto_sub >/dev/null || ! command -v mosquitto_pub >/dev/null; then
  echo "install mosquitto-clients (e.g. sudo apt install mosquitto-clients)" >&2
  exit 1
fi
