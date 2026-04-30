import logging
import os
import sys
import time

import paho.mqtt.client as mqtt
import requests

MQTT_HOST    = os.environ["MQTT_HOST"]
MQTT_PORT    = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER    = os.environ["MQTT_USER"]
MQTT_PASS    = os.environ["MQTT_PASS"]
GOTIFY_URL   = os.environ["GOTIFY_URL"].rstrip("/")
GOTIFY_TOKEN = os.environ["GOTIFY_TOKEN"]
GOTIFY_PRIO  = int(os.environ.get("GOTIFY_PRIORITY", "5"))

COOLDOWN_S = 30.0

LABELS = {
    "gate_open":   ("Brama", "otwarta"),
    "gate_closed": ("Brama", "zamknięta"),
}

# Per-key state. `seen_keys` tracks which (camera,label) pairs we've received
# at least one message for — the *first* message after startup only seeds
# state, it never fires a push, so a still-open gate at restart stays quiet.
last_count: dict[str, int] = {}
last_push_at: dict[str, float] = {}
seen_keys: set[str] = set()

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")


def push(title: str, message: str) -> None:
    r = requests.post(
        f"{GOTIFY_URL}/message",
        params={"token": GOTIFY_TOKEN},
        json={"title": title, "message": message, "priority": GOTIFY_PRIO},
        timeout=5,
    )
    r.raise_for_status()


def on_connect(client, _userdata, _flags, rc, *_):
    if rc != 0:
        log.error("mqtt connect failed rc=%s", rc)
        sys.exit(1)
    for label in LABELS:
        client.subscribe(f"frigate/+/{label}", qos=0)
        log.info("subscribed frigate/+/%s", label)


def on_message(_client, _userdata, msg):
    try:
        count = int(msg.payload.decode().strip())
    except ValueError:
        return
    parts = msg.topic.split("/")
    if len(parts) != 3:
        return
    _, camera, label = parts
    if label not in LABELS:
        return
    key = f"{camera}/{label}"

    if key not in seen_keys:
        seen_keys.add(key)
        last_count[key] = count
        log.info("seeded %s=%d (no push on first message)", key, count)
        return

    prev = last_count.get(key, 0)
    last_count[key] = count
    if not (prev == 0 and count >= 1):
        return

    now = time.monotonic()
    elapsed = now - last_push_at.get(key, 0.0)
    if elapsed < COOLDOWN_S:
        log.info("cooldown suppressed %s for %s (%.1fs left)",
                 label, camera, COOLDOWN_S - elapsed)
        return

    title, body = LABELS[label]
    try:
        push(title, f"{body} ({camera})")
        last_push_at[key] = now
        log.info("pushed %s %s for %s", title, body, camera)
    except Exception as e:
        log.exception("gotify push failed: %s", e)


def main() -> None:
    client = mqtt.Client(
        client_id="frigate-gotify-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
