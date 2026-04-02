# Chatsune

Privacy-first, self-hosted, multi-user AI companion platform.

## Prerequisites

- [Docker](https://docs.docker.com/get-docker/) and Docker Compose
- [uv](https://docs.astral.sh/uv/) (for local development)

## Quick Start

```bash
# Copy environment template and configure
cp .env.example .env
# Edit .env — at minimum change MASTER_ADMIN_PIN and JWT_SECRET

# Start services
docker compose up -d

# Verify
curl http://localhost:8000/api/health
# {"status":"ok"}
```

## Initial Setup

Create the master admin account (one-time):

```bash
curl -X POST http://localhost:8000/api/setup \
  -H "Content-Type: application/json" \
  -d '{
    "pin": "your-configured-pin",
    "username": "admin",
    "email": "admin@example.com",
    "password": "your-secure-password"
  }'
```

## Environment Variables

| Variable | Description | Example |
|---|---|---|
| `MASTER_ADMIN_PIN` | PIN for initial master admin setup | `change-me-1234` |
| `JWT_SECRET` | Secret for signing JWTs. Generate with `openssl rand -hex 32` | (random hex string) |
| `MONGODB_URI` | MongoDB connection string (must include `replicaSet=rs0`) | `mongodb://mongodb:27017/chatsune?replicaSet=rs0` |
| `REDIS_URI` | Redis connection string | `redis://redis:6379/0` |

## Development

```bash
# Install backend dependencies
cd backend && uv sync --all-extras && cd ..

# Run tests (requires Docker services running)
docker compose up -d mongodb redis
uv run --project backend pytest tests/ -v
```

## Architecture

See [CLAUDE.md](CLAUDE.md) for full architectural documentation.
