#!/usr/bin/env bash
# Publish a single message as if Frigate had sent it. Takes the full topic and
# free-form payload — quote either if it contains spaces (Frigate classification
# labels do).
# Usage: ./scripts/spoof.sh <topic> [payload]
#   ./scripts/spoof.sh 'frigate/Podjazd/classification/<MODEL>' 'Brama otwarta'
#   ./scripts/spoof.sh 'frigate/Podjazd/classification/<MODEL>' 'Brama zamknieta'
#   ./scripts/spoof.sh frigate/Podjazd/gate_open 1
source "$(dirname "$0")/_lib.sh"
TOPIC="${1:?usage: spoof.sh <topic> [payload]}"
PAYLOAD="${2-}"
echo "publish $TOPIC = $PAYLOAD" >&2
exec mosquitto_pub \
  -h "$MQTT_HOST" -p "$MQTT_PORT" \
  -u "$MQTT_USER" -P "$MQTT_PASS" \
  -t "$TOPIC" -m "$PAYLOAD"
