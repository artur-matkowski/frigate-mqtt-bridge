#!/usr/bin/env bash
# Publish a single message as if Frigate had sent it. Takes the full topic
# verbatim, so quote it if it contains spaces (Frigate classification labels do).
# Usage: ./scripts/spoof.sh <topic> [payload]
#   ./scripts/spoof.sh 'frigate/Podjazd/classification/Brama otwarta' 1
#   ./scripts/spoof.sh 'frigate/Podjazd/classification/Brama zamknieta' 1
#   ./scripts/spoof.sh frigate/Podjazd/gate_open 1
source "$(dirname "$0")/_lib.sh"
TOPIC="${1:?usage: spoof.sh <topic> [payload]}"
PAYLOAD="${2-}"
echo "publish $TOPIC = $PAYLOAD" >&2
exec mosquitto_pub \
  -h "$MQTT_HOST" -p "$MQTT_PORT" \
  -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t "$TOPIC" -m "$PAYLOAD"
