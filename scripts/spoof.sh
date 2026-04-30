#!/usr/bin/env bash
# Publish a single message as if Frigate had sent it.
# Usage: ./scripts/spoof.sh <label> <camera> [count]
#   ./scripts/spoof.sh gate_open Podjazd 1
#   ./scripts/spoof.sh gate_closed Podjazd 0
source "$(dirname "$0")/_lib.sh"
LABEL="${1:?usage: spoof.sh <label> <camera> [count]}"
CAMERA="${2:?usage: spoof.sh <label> <camera> [count]}"
COUNT="${3:-1}"
TOPIC="frigate/$CAMERA/$LABEL"
echo "publish $TOPIC = $COUNT" >&2
exec mosquitto_pub \
  -h "$MQTT_HOST" -p "$MQTT_PORT" \
  -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t "$TOPIC" -m "$COUNT"
