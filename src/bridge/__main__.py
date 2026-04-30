import logging
import os
import re
import sys
from collections import defaultdict
from dataclasses import dataclass

import paho.mqtt.client as mqtt
from paho.mqtt.client import topic_matches_sub
import requests

MQTT_HOST    = os.environ["MQTT_HOST"]
MQTT_PORT    = int(os.environ.get("MQTT_PORT", "1883"))
MQTT_USER    = os.environ["MQTT_USER"]
MQTT_PASS    = os.environ["MQTT_PASS"]
GOTIFY_URL   = os.environ["GOTIFY_URL"].rstrip("/")
GOTIFY_TOKEN = os.environ["GOTIFY_TOKEN"]
GOTIFY_PRIO  = int(os.environ.get("GOTIFY_PRIORITY", "5"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("bridge")


@dataclass
class Forward:
    n: int
    topics: list[str]
    values: set[str] | None
    title: str
    message: str
    priority: int


class _SafeDict(dict):
    def __missing__(self, key):
        return ""


_SLOT_RE = re.compile(r"^FORWARD_(\d+)_([A-Z]+)$")


def parse_forwards() -> list[Forward]:
    raw: dict[int, dict[str, str]] = defaultdict(dict)
    for k, v in os.environ.items():
        m = _SLOT_RE.match(k)
        if m:
            raw[int(m.group(1))][m.group(2)] = v

    forwards: list[Forward] = []
    for n in sorted(raw):
        slot = raw[n]
        topic_raw = slot.get("TOPIC", "").strip()
        if not topic_raw:
            log.warning("FORWARD_%d_* defined without _TOPIC — skipping", n)
            continue
        topics = [t.strip() for t in topic_raw.split(",") if t.strip()]
        values_raw = slot.get("VALUES", "").strip()
        values = (
            {v.strip() for v in values_raw.split(",") if v.strip()}
            if values_raw
            else None
        )
        priority = int(slot["PRIORITY"]) if "PRIORITY" in slot else GOTIFY_PRIO
        forwards.append(
            Forward(
                n=n,
                topics=topics,
                values=values,
                title=slot.get("TITLE", "{topic}"),
                message=slot.get("MESSAGE", "{payload}"),
                priority=priority,
            )
        )
    return forwards


FORWARDS = parse_forwards()


def push(title: str, message: str, priority: int) -> None:
    r = requests.post(
        f"{GOTIFY_URL}/message",
        params={"token": GOTIFY_TOKEN},
        json={"title": title, "message": message, "priority": priority},
        timeout=5,
    )
    r.raise_for_status()


def render(template: str, topic: str, payload: str) -> str:
    parts = topic.split("/")
    camera = parts[1] if len(parts) >= 2 else ""
    return template.format_map(_SafeDict(topic=topic, payload=payload, camera=camera))


def on_connect(client, _userdata, _flags, rc, *_):
    if rc != 0:
        log.error("mqtt connect failed rc=%s", rc)
        sys.exit(1)
    seen: set[str] = set()
    for fwd in FORWARDS:
        for t in fwd.topics:
            if t in seen:
                continue
            seen.add(t)
            client.subscribe(t, qos=0)
            log.info("subscribed %s", t)


def on_message(_client, _userdata, msg):
    payload = msg.payload.decode(errors="replace").strip()
    fired = 0
    for fwd in FORWARDS:
        if not any(topic_matches_sub(t, msg.topic) for t in fwd.topics):
            continue
        if fwd.values is not None and payload not in fwd.values:
            log.info(
                "FORWARD_%d dropped (value filter): topic=%s payload=%r",
                fwd.n, msg.topic, payload,
            )
            continue
        title = render(fwd.title, msg.topic, payload)
        message = render(fwd.message, msg.topic, payload)
        try:
            push(title, message, fwd.priority)
            log.info(
                "FORWARD_%d pushed: title=%r message=%r (topic=%s)",
                fwd.n, title, message, msg.topic,
            )
            fired += 1
        except Exception as e:
            log.exception("FORWARD_%d gotify push failed: %s", fwd.n, e)
    if fired == 0:
        log.debug("no forward matched topic=%s", msg.topic)


def main() -> None:
    if not FORWARDS:
        log.error("no FORWARD_<N>_TOPIC env vars set — nothing to forward")
        sys.exit(1)
    log.info("parsed %d forwards", len(FORWARDS))
    for fwd in FORWARDS:
        log.info(
            "  FORWARD_%d topics=%s values=%s title=%r message=%r priority=%d",
            fwd.n,
            fwd.topics,
            sorted(fwd.values) if fwd.values is not None else "*",
            fwd.title,
            fwd.message,
            fwd.priority,
        )

    client = mqtt.Client(
        client_id="frigate-mqtt-bridge",
        callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
    )
    client.username_pw_set(MQTT_USER, MQTT_PASS)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(MQTT_HOST, MQTT_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
