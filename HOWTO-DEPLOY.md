# HOWTO: Deploy Chatsune behind Traefik

This guide walks you through a first production-style deployment of Chatsune
on a single VPS, behind an existing Traefik reverse proxy with automatic
Let's Encrypt TLS. It targets the setup most people actually run: Traefik
handles the edge, and Chatsune runs as a stack of containers on the same
host, joining Traefik's Docker network.

Early alpha: there are no versioned releases yet — `latest` tracks the tip
of `master`. Once we cut the first tag, swap `:latest` for `:v0.1.0` (etc.)
in `docker-compose.prod.yml`.

---

## Prerequisites

- A VPS with Docker Engine ≥ 24 and the Compose v2 plugin
- **Traefik v3** already running on the host, configured with:
  - A `websecure` entrypoint on `:443`
  - A Let's Encrypt cert resolver named `letsencrypt`
  - A Docker provider bound to an external network named `traefik`
  - If your resolver or network uses different names, adjust the labels in
    `docker-compose.prod.yml` accordingly
- A DNS A/AAAA record pointing your chosen hostname at the VPS
- A GitHub account with access to pull images from
  `ghcr.io/symphonic-navigator/chatsune-*`

If your Traefik network is named differently (e.g. `web`, `proxy`), change
both the `networks.traefik.name` entry and every `traefik.docker.network`
label in `docker-compose.prod.yml`.

---

## Topology

Chatsune is designed for **same-origin deployment**. Everything lives on one
hostname, and Traefik routes by path:

```
https://chatsune.example.com/          → frontend (nginx, static SPA)
https://chatsune.example.com/api/*     → backend  (FastAPI)
https://chatsune.example.com/ws        → backend  (WebSocket)
```

This is the recommended topology because:

- **No CORS complications.** The browser treats API calls as same-origin.
- **No cross-domain cookie issues.** The refresh-token cookie is host-only.
- **The frontend bundle needs no runtime config.** `VITE_API_URL` and
  `VITE_WS_URL` stay empty, so the app uses `window.location` for both the
  API base and the WebSocket URL (see `frontend/src/core/api/client.ts` and
  `frontend/src/core/websocket/connection.ts`).

A split-domain setup (`app.example.com` + `api.example.com`) is possible but
needs extra work — see *Alternative: split-domain deploy* at the bottom.

---

## 1. Make the GHCR images pullable

The `Docker Build & Push` workflow publishes two images on every push to
`master`:

- `ghcr.io/symphonic-navigator/chatsune-frontend:latest`
- `ghcr.io/symphonic-navigator/chatsune-backend:latest`

GHCR packages default to **private** visibility. You have two options:

**Option 1 — Make them public (simplest).** On GitHub, go to your profile →
`Packages` → click each chatsune image → `Package settings` → scroll to
`Danger Zone` → `Change visibility` → `Public`. No VPS-side login needed.

**Option 2 — Keep them private.** Generate a Personal Access Token with the
`read:packages` scope, then on the VPS:

```bash
echo "$GHCR_TOKEN" | docker login ghcr.io -u <your-gh-username> --password-stdin
```

Either is fine. Public is less friction for a small alpha.

---

## 2. Check out the repo on the VPS

You only need the compose file and the env template. Everything else ships
inside the images.

```bash
git clone https://github.com/symphonic-navigator/chatsune.git /opt/chatsune
cd /opt/chatsune
```

(You can also copy just `docker-compose.prod.yml` and `.env.prod.example`
to an arbitrary directory if you don't want a full clone on the VPS.)

---

## 3. Generate secrets and fill in `.env`

```bash
cp .env.prod.example .env
```

Edit `.env` and fill each value:

```bash
# Hostname — used by both Traefik routing and backend CORS
CHATSUNE_HOST=chatsune.example.com

# Fresh random value, rotate before first login
MASTER_ADMIN_PIN=$(openssl rand -hex 8)

# 32 bytes hex for JWT signing
JWT_SECRET=$(openssl rand -hex 32)

# Fernet key for encrypting stored API keys at rest
ENCRYPTION_KEY=$(python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")

# 32-byte pepper for /kdf-params user-enumeration defence
KDF_PEPPER=$(python3 -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())")
```

These five values must be set. Everything else in the template is optional.

Lock down the file:

```bash
chmod 600 .env
```

---

## 4. Create the Traefik network (once)

Skip this if you already have one:

```bash
docker network create traefik
```

---

## 5. Pull and start

```bash
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml up -d
```

Watch the startup:

```bash
docker compose -f docker-compose.prod.yml logs -f
```

What should happen:

1. `mongodb` starts, first healthcheck initialises `rs0`, subsequent probes
   report `ok`
2. `redis` starts, healthcheck passes
3. `backend` starts once both dependencies report healthy
4. `frontend`'s nginx entrypoint runs the Vite env substitution script
   (a no-op when `VITE_API_URL` / `VITE_WS_URL` are empty), then nginx
   starts serving on port 80
5. Traefik picks up the container labels and routes the hostname

Hit `https://chatsune.example.com` in a browser — you should see the login
screen.

---

## 6. First-time admin setup

Chatsune creates no users automatically. The very first request to
`/api/setup` with the `MASTER_ADMIN_PIN` in the body creates the master
admin. Do this once, then never again:

```bash
curl -X POST https://chatsune.example.com/api/setup \
  -H "Content-Type: application/json" \
  -d '{
    "pin": "<value of MASTER_ADMIN_PIN>",
    "username": "admin",
    "email": "you@example.com",
    "password": "<strong password>"
  }'
```

After that, log in through the UI. The PIN will no longer do anything.

You can clear `MASTER_ADMIN_PIN` from `.env` afterwards — but the backend
requires the var to be present at startup, so just leave some value in it.
Consider rotating it.

---

## 7. Updating to a new image

The workflow tags every build with `master`, `latest`, and `sha-<short>`.
`latest` always points at the tip of `master`.

```bash
cd /opt/chatsune
git pull                                                 # refresh compose file
docker compose -f docker-compose.prod.yml pull           # grab new images
docker compose -f docker-compose.prod.yml up -d          # recreate changed ones
```

Compose diffs image digests and only recreates containers whose image
changed, so the database keeps running.

### Pinning a specific build

If you want to deploy an exact commit instead of `latest`, edit
`docker-compose.prod.yml`:

```yaml
backend:
  image: ghcr.io/symphonic-navigator/chatsune-backend:sha-eaeadf3
frontend:
  image: ghcr.io/symphonic-navigator/chatsune-frontend:sha-eaeadf3
```

Once we start cutting semver tags you can pin to `:v0.1.0` instead.

---

## 8. Backups

The stateful data lives in four named Docker volumes:

| Volume           | Contents                                   |
|------------------|---------------------------------------------|
| `chatsune_mongodb_data` | MongoDB databases (users, chats, memories, journal) |
| `chatsune_redis_data`   | Refresh tokens + event streams (24 h TTL; losing this only forces clients to reconnect) |
| `chatsune_uploads_data` | User file uploads                    |
| `chatsune_avatars_data` | Persona profile pictures             |

Minimum-viable backup with `mongodump`:

```bash
docker compose -f docker-compose.prod.yml exec mongodb \
  mongodump --archive --db=chatsune > chatsune-$(date +%F).archive
```

Restore:

```bash
docker compose -f docker-compose.prod.yml exec -T mongodb \
  mongorestore --archive --drop < chatsune-YYYY-MM-DD.archive
```

For uploads/avatars, `tar` the volume contents:

```bash
docker run --rm \
  -v chatsune_uploads_data:/data \
  -v "$PWD":/backup \
  alpine tar czf /backup/uploads-$(date +%F).tar.gz -C /data .
```

---

## 9. Troubleshooting

### Traefik returns 404

- `docker compose -f docker-compose.prod.yml ps` — are frontend and backend
  running and healthy?
- `docker inspect chatsune-frontend-1 | grep -A5 Networks` — is it on the
  `traefik` network?
- In the Traefik dashboard, look for routers named `chatsune-frontend` and
  `chatsune-backend`. If they're missing, the `traefik.docker.network` label
  name probably doesn't match your actual Traefik network.

### Login works, but WebSocket never connects

- Browser devtools → Network → WS filter. Does the `/ws` handshake 404 or
  101?
- 404 → the backend router's PathPrefix rule is missing `/ws`. Check the
  `chatsune-backend` router rule in `docker-compose.prod.yml`.
- 101 then immediately closes → backend CORS. `CORS_ALLOWED_ORIGINS` must
  include the full `https://${CHATSUNE_HOST}` value.

### Backend crashes on startup with `encryption_key must decode to 32 bytes`

`ENCRYPTION_KEY` isn't a valid Fernet key. Regenerate:

```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

### Backend crashes on startup with `kdf_pepper Field required` or `must decode to exactly 32 bytes`

`KDF_PEPPER` is missing or malformed. Generate a fresh one and add it to `.env`:

```bash
python3 -c "import secrets, base64; print('KDF_PEPPER=' + base64.urlsafe_b64encode(secrets.token_bytes(32)).decode())"
```

Set once and keep the value stable across deploys — rotating it invalidates
the deterministic pseudo-salts and shifts the user-enumeration defence
boundary. Losing the value does not decrypt any user data.

### Frontend loads but all API calls 404

Either Traefik priority is wrong (frontend router catches `/api/*`) or
`VITE_API_URL` was built with a bad placeholder. The backend router must
have **higher priority** than the frontend router — the supplied compose
file sets `priority=100` vs `priority=1`, which is correct.

Check what nginx actually ships:

```bash
docker compose -f docker-compose.prod.yml exec frontend \
  grep -o '__VITE_[A-Z_]*__' /usr/share/nginx/html/assets/index-*.js || echo "no placeholders left"
```

If placeholders are still there, the entrypoint script didn't run — check
frontend container logs for sed errors.

### Changed `VITE_API_URL` / `VITE_WS_URL`, no effect

The substitution is in-place and runs once per container lifetime. Force
a recreate:

```bash
docker compose -f docker-compose.prod.yml up -d --force-recreate frontend
```

### MongoDB never becomes healthy

The replica set needs one successful `rs.initiate()`. Check:

```bash
docker compose -f docker-compose.prod.yml logs mongodb
docker compose -f docker-compose.prod.yml exec mongodb \
  mongosh --quiet --eval "rs.status()"
```

If the volume is from an older non-RS install, `rs.initiate()` may refuse.
In that case, either recreate the volume (destroys data) or run
`rs.initiate()` manually.

---

## Alternative: split-domain deploy

If you want the backend on its own hostname (`api.chatsune.example.com`):

1. Add DNS for the second host.
2. Add a second router block in the backend service labels:

    ```yaml
    - "traefik.http.routers.chatsune-backend.rule=Host(`api.${CHATSUNE_HOST}`)"
    ```

3. Frontend needs real URLs baked in at runtime:

    ```yaml
    frontend:
      environment:
        VITE_API_URL: "https://api.${CHATSUNE_HOST}"
        VITE_WS_URL:  "wss://api.${CHATSUNE_HOST}"
    ```

4. Backend CORS must include the frontend origin:

    ```yaml
    backend:
      environment:
        CORS_ALLOWED_ORIGINS: '["https://${CHATSUNE_HOST}"]'
    ```

5. Because the refresh-token cookie must be readable from both hosts, set
   `COOKIE_DOMAIN=.chatsune.example.com` in `.env`.

6. Recreate the frontend so the new `VITE_*` values are substituted:

    ```bash
    docker compose -f docker-compose.prod.yml up -d --force-recreate frontend
    ```

This is strictly more complex than the same-origin setup for no functional
benefit. Only go this route if you have an existing reason (legacy CNAMEs,
separate TLS terminations, etc.).
