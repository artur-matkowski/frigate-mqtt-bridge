#!/usr/bin/env bash
# 1 -> 0 -> 1 sequence. Exercises the rising-edge detector and the cooldown:
#   - first  `1`  fires a push (first message after restart only seeds — run this
#                  twice if you just restarted the bridge)
#   - then   `0`  resets edge state, no push
#   - second `1`  is within COOLDOWN_S (30s) of the first push, should be suppressed
# Usage: ./scripts/spoof-cycle.sh <label> <camera>
source "$(dirname "$0")/_lib.sh"
LABEL="${1:?usage: spoof-cycle.sh <label> <camera>}"
CAMERA="${2:?usage: spoof-cycle.sh <label> <camera>}"
TOPIC="frigate/$CAMERA/$LABEL"

pub() {
  mosquitto_pub \
    -h "$MQTT_HOST" -p "$MQTT_PORT" \
    -u "$MQTT_USER" -P "$MQTT_PASS" \
    -t "$TOPIC" -m "$1"
  echo "→ $TOPIC = $1"
}

pub 1
sleep 2
pub 0
sleep 2
pub 1
