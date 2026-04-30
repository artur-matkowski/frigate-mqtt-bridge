# Guide: Push Frigate gate-state events to Gotify via MQTT (Portainer workflow)

## Context

Frigate (VM A) and Gotify (VM B) both run in Docker, managed via Portainer. Gotify already delivers Grafana pushes. You just added custom object labels for gate state (`gate_open` / `gate_closed`) on Frigate and want a notification on each state change. Frigate has no native Gotify integration, so we bridge through MQTT:

```
Frigate (VM A) ──MQTT──▶ Mosquitto (VM A) ──MQTT──▶ bridge (VM B) ──HTTP──▶ Gotify (VM B) ──push──▶ phone
```

This guide is **documentation only** — nothing runs against your hosts from here. Every "deploy" step is a click in the Portainer UI on the relevant VM.

### Why this shape
- Mosquitto colocates with Frigate so the highest-volume publisher writes locally.
- Bridge sits on the Gotify VM so the Gotify POST is over the local Docker network and only one cross-VM port (1883) is opened.
- The bridge is a small Python service shipped as a pre-built image on `ghcr.io` — no custom build on the target VM, no bind-mounted script.

### Scope of v1
- Plain-text push: title and body are templates per forward, with `{topic}` / `{payload}` / `{camera}` substitution.
- Pure pass-through: every MQTT message that matches a configured forward fires a Gotify push. No edge detection, no cooldown.
- Forwards are configured via `FORWARD_<N>_*` env vars — multiple slots, each subscribing to one or more topic filters, with optional payload-value filtering and per-slot priority.
- One Gotify Application reused for all forwarded events.
- Snapshots, TLS, structured logs, retained-message handling → see "Later".

---

## Workflow assumptions (Portainer)

- You manage Docker via **Portainer Standalone** on each VM (not Swarm).
- New services are deployed as **Stacks** using Portainer's **Web editor**.
- The `mosquitto.conf` file is placed on VM A's filesystem **once** via SSH/SFTP — Portainer's web editor only handles compose YAML, not arbitrary side files. After that, all lifecycle (restart, update, logs, exec) is in the UI.
- The bridge has no host-side support files: it ships as a pre-built image on `ghcr.io`, and its compose file pastes as-is into Portainer.
- One-off commands like creating MQTT users run through Portainer's **Container Console** (`Containers → mosquitto → Console → Connect`), not `docker compose run`.

If you'd rather avoid SSH for `mosquitto.conf` too, put it in a git repo and use Portainer's **"Repository"** stack source instead of "Web editor" — that mode pulls compose + side files together.

---

## Prerequisites checklist

- [ ] Frigate is publishing the topics you intend to forward (e.g. classification topics like `frigate/<camera>/classification/<label>`, or per-object topics like `frigate/<camera>/<label>`). Confirm with `./scripts/sniff-frigate.sh` before configuring forwards.
- [ ] Portainer is reachable on both VMs and you can create stacks.
- [ ] You know the LAN IPs — call them `FRIGATE_HOST` and `GOTIFY_HOST` below.
- [ ] You can `ssh` (or SFTP) into both VMs to drop ~3 small files.
- [ ] Gotify is reachable from the Gotify VM itself.

---

## Step 1 — Deploy Mosquitto on VM A (Frigate host)

### 1a. Drop the config file on the host (SSH once)

On VM A, pick a stable path — e.g. `/opt/stacks/mosquitto/`:
```
sudo mkdir -p /opt/stacks/mosquitto/config /opt/stacks/mosquitto/data /opt/stacks/mosquitto/log
sudo chown -R 1883:1883 /opt/stacks/mosquitto    # eclipse-mosquitto runs as uid 1883
```

Create `/opt/stacks/mosquitto/config/mosquitto.conf`:
```
listener 1883
allow_anonymous false
password_file /mosquitto/config/passwd
persistence true
persistence_location /mosquitto/data/
log_dest stdout
```

Create an empty `passwd` file (Mosquitto refuses to start if the file is missing):
```
sudo touch /opt/stacks/mosquitto/config/passwd
sudo chown 1883:1883 /opt/stacks/mosquitto/config/passwd
```

### 1b. Create the stack in Portainer (VM A)

**Stacks → Add stack → Web editor**, name `mosquitto`. Paste:
```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    ports:
      - "1883:1883"
    volumes:
      - /opt/stacks/mosquitto/config:/mosquitto/config
      - /opt/stacks/mosquitto/data:/mosquitto/data
      - /opt/stacks/mosquitto/log:/mosquitto/log
```

Click **Deploy the stack**. The container will start but the listener is auth-required and the passwd file is empty, so nobody can connect yet — that's fine.

### 1c. Create MQTT users via Portainer Console

**Containers → mosquitto → Console → Connect** (shell `/bin/sh`). The empty `passwd` file from 1a already exists, so use `-b` (add/update) without `-c` — Mosquitto 2.x refuses `-c` against an existing file:
```
mosquitto_passwd -b /mosquitto/config/passwd frigate <FRIGATE_MQTT_PASS>
mosquitto_passwd -b /mosquitto/config/passwd bridge  <BRIDGE_MQTT_PASS>
exit
```
(If you skipped the `touch passwd` step in 1a, run the first command with `-c -b` to create the file, then the second with just `-b`.)

Then **Containers → mosquitto → Restart** so Mosquitto re-reads the file.

### 1d. Firewall

Open TCP 1883 on VM A only to `GOTIFY_HOST`. Portainer doesn't manage host firewall, so do it on the host:
```
sudo ufw allow from <GOTIFY_HOST> to any port 1883 proto tcp
```
(If you don't want to pierce the firewall, run the bridge on VM A — see "Later".)

---

## Step 2 — Enable MQTT in Frigate (VM A)

Find your Frigate stack in Portainer. Locate the Frigate config — typically a bind-mounted `frigate.yml` (or `frigate.cfg`) on the host. Edit that file via SSH and replace `mqtt: enabled: false` with:

```yaml
mqtt:
  enabled: true
  host: mosquitto             # works if Frigate and Mosquitto share a docker network — see note below
  port: 1883
  user: frigate
  password: <FRIGATE_MQTT_PASS>
  topic_prefix: frigate
  client_id: frigate
  stats_interval: 60
```

**Network note.** For `host: mosquitto` to resolve, Frigate's container must be on the same Docker network as Mosquitto. Two options:

- **Option A (simplest)**: merge the `mosquitto:` service into the existing Frigate stack instead of running it as a separate stack. In Portainer: edit the Frigate stack, paste the `mosquitto:` service into the same `services:` block, redeploy. Frigate auto-shares the stack's default network.
- **Option B**: keep them as separate stacks but create an external network. Run once on the host: `docker network create iot`. In each stack add:
  ```yaml
  networks:
    iot:
      external: true
  ```
  and attach both services to `iot`.

If you don't want to bother with networks at all, set `host: <FRIGATE_HOST>` (the host's LAN IP) — Frigate will reach Mosquitto via the published `1883` port. Slightly less elegant but works.

After saving the config: **Stacks → frigate → Update / Recreate** (or just restart the Frigate container). Watch **Containers → frigate → Logs** for `mqtt: connected`.

---

## Step 3 — Smoke-test from VM B

You don't need a stack for this — just a one-shot container via Portainer on VM B:

**Containers → Add container** → image `eclipse-mosquitto:2` → Command override:
```
mosquitto_sub -h <FRIGATE_HOST> -p 1883 -u bridge -P <BRIDGE_MQTT_PASS> -v -t frigate/#
```
Disable "Auto-remove" so logs persist; **Deploy**. Open **Logs**, then walk past the gate.

You should see your real Frigate topics, e.g.:
```
frigate/Podjazd/classification/Brama otwarta 1
frigate/Podjazd/classification/Brama zamknieta 1
frigate/Podjazd/<some_label> 1
```
If you only see `frigate/<camera>/all` and no per-label or per-classification topics, your detectors aren't firing the way you expect — fix that before proceeding. If you see no `frigate/...` topics at all, Frigate didn't connect to MQTT — re-check Step 2.

**Write down the exact topic strings you see** — they go straight into `FORWARD_<N>_TOPIC` in Step 5. Topic segments may legitimately contain spaces (Frigate classification labels often do).

Stop and remove the smoke-test container when done.

Reference: <https://docs.frigate.video/integrations/mqtt/>.

---

## Step 4 — Create a Gotify Application token

In the Gotify web UI: **Apps → Create Application** → name `Frigate`. Copy the token — call it `GOTIFY_TOKEN`. Keeping it as its own app lets you mute Frigate alone if you ever need to.

Sanity check via Portainer on VM B — **Containers → Add container** → image `curlimages/curl:latest` → command override:
```
curl -X POST "http://gotify/message?token=<GOTIFY_TOKEN>" -F title=Test -F message=hello
```
…and attach the container to the same network as Gotify before deploying. You should get a push within a couple of seconds. Remove the test container after.

---

## Step 5 — Deploy the bridge on VM B (Gotify host)

The bridge is a small Python service published as a container image at `ghcr.io/artur-matkowski/frigate-mqtt-bridge`. You build it once on a dev box, push to ghcr.io, then pull it on the target VM. The same image and compose work on either VM — only `.env` and the network name differ.

### Project layout (this repo)

```
frigate-mqtt-bridge/
├── src/bridge/__main__.py    # bridge logic (env-driven topic→Gotify forwards)
├── Dockerfile                # multi-stage, non-root user
├── requirements.txt          # paho-mqtt==2.*, requests==2.*
├── docker-compose.yml        # registry-only, paste-into-Portainer ready
├── .env.example              # config template
├── Makefile                  # build / push / release / login
└── scripts/                  # debug shell tools (sniff/spoof) — see "Debugging"
```

### 5a. Build and push the image (from your dev box, once per release)

You need:
- Docker on the dev box.
- `gh` CLI authenticated with `write:packages` scope: `gh auth refresh -s write:packages`.

Then from the project root:
```
make login                  # docker login ghcr.io using the gh CLI's token
make release VERSION=v1     # build :v1 + :latest, push both to ghcr.io
```

After a successful push, the image is at `ghcr.io/artur-matkowski/frigate-mqtt-bridge:v1` (and `:latest`). It will appear under **GitHub → your profile → Packages**. By default, ghcr packages are private — link it to a repo (the `org.opencontainers.image.source` label points at one) and toggle visibility on the package page if you want anonymous pulls.

### 5b. Create the stack in Portainer (VM B)

**Stacks → Add stack → Web editor**, name `frigate-mqtt-bridge`. Paste:

```yaml
services:
  bridge:
    image: ghcr.io/artur-matkowski/frigate-mqtt-bridge:latest
    container_name: frigate-mqtt-bridge
    restart: unless-stopped
    environment:
      MQTT_HOST: <FRIGATE_HOST>
      MQTT_PORT: "1883"
      MQTT_USER: bridge
      MQTT_PASS: <BRIDGE_MQTT_PASS>
      GOTIFY_URL: http://<GOTIFY_HOST>:<GOTIFY_PORT>
      GOTIFY_TOKEN: <GOTIFY_TOKEN>
      GOTIFY_PRIORITY: "5"
      # One forward slot per (set of) topic filter(s). N can be any integer.
      FORWARD_1_TOPIC: "frigate/+/classification/Brama otwarta,frigate/+/classification/Brama zamknieta"
      FORWARD_1_TITLE: "Brama"
      FORWARD_1_MESSAGE: "{payload} ({camera})"
      # Optional value filter — only fires when payload is exactly "1":
      # FORWARD_2_TOPIC: "frigate/+/gate_open"
      # FORWARD_2_TITLE: "Brama"
      # FORWARD_2_MESSAGE: "otwarta"
      # FORWARD_2_VALUES: "1"
      # FORWARD_2_PRIORITY: "5"
```

Substitute the placeholders directly in the YAML before deploying. All connections are over LAN IPs — no Docker hostnames, no shared networks — so Compose's auto-created default network is enough and no `networks:` block is needed.

Forward semantics:
- `FORWARD_<N>_TOPIC` is comma-separated — one slot can subscribe to several filters (`+`/`#` wildcards allowed; spaces in segments are fine).
- `FORWARD_<N>_VALUES` (optional, comma-separated) restricts forwarding to those exact payloads (after `strip()`). Unset = forward every payload.
- `FORWARD_<N>_TITLE` / `FORWARD_<N>_MESSAGE` support `{topic}`, `{payload}`, `{camera}` placeholders. Defaults: `{topic}` and `{payload}`.
- `FORWARD_<N>_PRIORITY` falls back to `GOTIFY_PRIORITY`.

**Private package?** If you didn't make the ghcr package public, the VM needs a one-time `docker login ghcr.io -u artur-matkowski` with a `read:packages`-scoped PAT. Public packages: nothing to set up.

Click **Deploy the stack**. **Containers → frigate-mqtt-bridge → Logs** should show:
```
... INFO parsed 1 forwards
... INFO   FORWARD_1 topics=['frigate/+/classification/Brama otwarta', 'frigate/+/classification/Brama zamknieta'] values=* title='Brama' message='{payload} ({camera})' priority=5
... INFO subscribed frigate/+/classification/Brama otwarta
... INFO subscribed frigate/+/classification/Brama zamknieta
```

### 5c. Or deploy via SSH on VM B (no Portainer)

```
sudo mkdir -p /opt/stacks/frigate-mqtt-bridge
cd /opt/stacks/frigate-mqtt-bridge
# place docker-compose.yml and .env here (copy from this repo)
docker compose pull
docker compose up -d
docker compose logs -f bridge
```

### Bridge on VM A instead

Same image, different `.env` and network:
- `MQTT_HOST=mosquitto` (container name on the shared network)
- `GOTIFY_URL=http://<GOTIFY_HOST>:<gotify-port>` (no longer same network as Gotify)
- `networks:` in compose: whatever shares with Mosquitto

This closes the cross-VM 1883 hole at the cost of one cross-VM HTTP hop per push.

---

## Debugging — peek and spoof MQTT messages

The MQTT broker is the central nerve of this pipeline; a couple of `.sh` scripts in `scripts/` let you peek at traffic and synthesize messages without involving Frigate or your phone. **They are dev-only — not part of the deployed image.**

**Prerequisite**: `mosquitto-clients` on whatever host you run them from (`sudo apt install mosquitto-clients` on Debian/Ubuntu). The scripts source `.env` from the project root, reusing the same MQTT credentials as the bridge — no second user to create.

### Peek with `./scripts/sniff.sh`

Listen to traffic. By default, **every topic on the broker** (`#` wildcard):

```
$ ./scripts/sniff.sh
sniffing <FRIGATE_HOST>:1883 topic=#  (Ctrl-C to stop)
frigate/available online
frigate/stats {"detection_fps": 0.0, ...}
frigate/Podjazd/classification/Brama otwarta 1
frigate/Podjazd/classification/Brama zamknieta 1
```

Restrict by passing a topic pattern:

```
./scripts/sniff.sh 'frigate/+/classification/#'   # all classifications across cameras
./scripts/sniff.sh 'frigate/events'               # rich JSON event stream
./scripts/sniff-frigate.sh                        # convenience: 'frigate/#'
```

MQTT wildcards: `#` matches any number of trailing topic segments; `+` matches exactly one segment. With no ACLs configured on Mosquitto, the bridge user can read everything, so `#` shows the entire broker.

### Spoof with `./scripts/spoof.sh`

Publish a fake message as if Frigate had sent it. The full topic is passed verbatim — quote it if it contains spaces. Usage: `spoof.sh <topic> [payload]` (payload defaults to empty):

```
./scripts/spoof.sh 'frigate/Podjazd/classification/Brama otwarta' 1
./scripts/spoof.sh 'frigate/Podjazd/classification/Brama zamknieta' 1
./scripts/spoof.sh frigate/Podjazd/gate_open 1
```

The bridge logs whether the message matched a forward and what got pushed (or why it was dropped):
```
... INFO FORWARD_1 pushed: title='Brama' message='1 (Podjazd)' (topic=frigate/Podjazd/classification/Brama otwarta)
... INFO FORWARD_2 dropped (value filter): topic=frigate/Podjazd/gate_open payload='0'
```

---

## Step 6 — End-to-end verification

1. **Mosquitto reachable from VM B** — in one terminal `./scripts/sniff.sh 'test/ping'`, in another `mosquitto_pub -h <FRIGATE_HOST> -p 1883 -u bridge -P <BRIDGE_MQTT_PASS> -t test/ping -m hi`. The sniff terminal should print the message.

2. **Bridge parsed and subscribed** — VM B → **Containers → frigate-mqtt-bridge → Logs**. See `parsed N forwards` and one `subscribed <filter>` line per unique filter. If a slot has misconfigured env, you'll see `FORWARD_<N>_* defined without _TOPIC — skipping`.

3. **Synthetic event** — `./scripts/spoof.sh 'frigate/Podjazd/classification/Brama otwarta' 1`. Bridge logs `FORWARD_1 pushed: title='Brama' message='1 (Podjazd)'`. Phone push within ~1 s.

4. **Value filter** — if you've configured a slot with `FORWARD_<N>_VALUES`, publish a non-matching payload and confirm `FORWARD_<N> dropped (value filter)` in the logs (no push). Then publish a matching payload — push fires.

5. **Real event** — physically trigger the underlying detector (move the gate, etc.), with `./scripts/sniff-frigate.sh` running in another terminal. Confirm the underlying topic traffic *and* the phone push.

6. **Restart safety** — **Containers → frigate-mqtt-bridge → Restart**. The bridge re-subscribes; no state to seed. If a topic you're subscribed to has retained messages, expect a push immediately on reconnect — classification topics aren't typically retained, but verify with `sniff` if in doubt.

---

## What sits where (summary)

On VM A (Frigate host):
- `/opt/stacks/mosquitto/config/mosquitto.conf` — placed via SSH.
- `/opt/stacks/mosquitto/config/passwd` — generated via Portainer Console.
- Portainer stack: `mosquitto` (or merged into the Frigate stack — recommended).
- Frigate config file: `mqtt:` block enabled.
- Host firewall: TCP 1883 from `GOTIFY_HOST`.

On VM B (Gotify host):
- Portainer stack: `frigate-mqtt-bridge`, image `ghcr.io/artur-matkowski/frigate-mqtt-bridge:latest`, attached to the Gotify network.
- `.env` (or Portainer stack env vars) with MQTT host/creds and Gotify URL/token.
- Gotify Application "Frigate" — token referenced from `.env`.

In this repo: bridge sources, packaging, deploy compose, and debug scripts. The image on `ghcr.io` is the deployable artifact; your homelab pulls and runs it.

---

## Later (deliberately out of v1)

- **Snapshot link / image** — Frigate's `http://<frigate>/api/<camera>/latest.jpg`. Switch Gotify body to Markdown via `extras: { "client::display": { contentType: "text/markdown" } }` and embed a markdown image, once you've decided whether VM B is allowed to reach Frigate's HTTP port.
- **Use `frigate/events` instead of per-label topics** — richer JSON (event id, score, zones), enables zone/score filtering. Worth it once gates aren't the only thing you alert on.
- **Healthcheck + structured JSON logs** — container reports unhealthy on persistent push failures; logs become Loki-pipeable.
- **Bridge on the Frigate VM instead** — collapse the cross-VM port. Move the stack to VM A, set `MQTT_HOST=mosquitto`, `GOTIFY_URL=http://<GOTIFY_HOST>:<port>`. Closes the firewall hole at the cost of an extra cross-VM hop per push (one short HTTP call instead of a persistent MQTT TCP session). Same image, different `.env`.
- **TLS on MQTT** — for LAN-only it's optional; if it leaves the LAN, switch the listener to 8883 with a cert and add `tls_set` in the bridge.
- **Multiple notification channels** — refactor `push()` into a list of dispatchers when there's a second sink (ntfy, Pushover, etc.). Don't generalize before two.
- **Per-forward cooldown / debounce** — currently every matched message fires a push. Add an opt-in `FORWARD_<N>_COOLDOWN_S` if a chatty topic produces too many notifications.
- **Ignore retained messages** — opt-in `FORWARD_<N>_IGNORE_RETAINED=1` so a bridge restart doesn't replay retained state pushes.
- **CI build & push** — GitHub Actions workflow that runs `make release` on tags. Avoids needing Docker on your dev box for releases.
- **Drop the bridge entirely** — if/when Frigate gains native webhook notifications upstream, the bridge becomes redundant. Today (Frigate 0.16) it doesn't.
