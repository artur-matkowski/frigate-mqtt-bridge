#!/usr/bin/env bash
# Listen to MQTT topics on the broker. Default: every topic (`#` wildcard).
# Usage: ./scripts/sniff.sh                  # sees everything
#        ./scripts/sniff.sh 'frigate/events' # restrict to one topic
source "$(dirname "$0")/_lib.sh"
TOPIC="${1:-#}"
echo "sniffing $MQTT_HOST:$MQTT_PORT topic=$TOPIC  (Ctrl-C to stop)" >&2
exec mosquitto_sub \
  -h "$MQTT_HOST" -p "$MQTT_PORT" \
  -u "$MQTT_USER" -P "$MQTT_PASS" \
  -v -t "$TOPIC"
