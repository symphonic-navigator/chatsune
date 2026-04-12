# Ollama Local Admin Tab

**Date:** 2026-04-12
**Scope:** Small — new read-only admin tab for Ollama Local diagnostics

## Summary

Add an "Ollama Local" tab to the admin modal that displays running models (`/api/ps`)
and available models (`/api/tags`) from a locally connected Ollama instance. Read-only,
no editing. Auto-refreshes every 5 seconds while active.

## Backend

Two new admin-only proxy endpoints in the LLM module handlers:

- `GET /api/llm/admin/ollama-local/ps` — forwards to `{OLLAMA_LOCAL_BASE_URL}/api/ps`
- `GET /api/llm/admin/ollama-local/tags` — forwards to `{OLLAMA_LOCAL_BASE_URL}/api/tags`

Both require `require_admin` dependency. On connection error, return HTTP 503 with
a JSON body `{ "detail": "..." }`. No new DTOs — responses are passed through as
plain dicts (this is a debug tool, not business logic).

The adapter's existing `httpx.AsyncClient` or a lightweight dedicated client can be
used. The base URL comes from `OLLAMA_LOCAL_BASE_URL` env var (default `http://localhost:11434`).

## Frontend

New component: `frontend/src/app/components/admin-modal/OllamaTab.tsx`

### Tab visibility

The "Ollama Local" tab is always shown in the admin modal (the provider is always
configured). Connection status is determined by whether the data request succeeds.

### Sub-tabs

Two sub-tabs within the component: **"Running (ps)"** (default) and **"Models (tags)"**.

### Polling

The active sub-tab's data is fetched on mount and every 5 seconds thereafter.
Polling stops when the tab is not active or the admin modal is closed.

### Connection error handling

If the backend returns 503 (or any error), display a centred message:
"No connection to Ollama Local" instead of the table. The polling continues
so recovery is automatic.

### PS table columns

| Column | Source field | Formatting |
|--------|-------------|------------|
| Name | `name` | as-is |
| Model | `model` | as-is |
| Size | `size` | human-readable bytes (e.g. "6.1 GB") |
| Parameters | `details.parameter_size` | as-is (e.g. "4.3B") |
| Quantisation | `details.quantization_level` | as-is (e.g. "Q4_K_M") |
| VRAM | `size_vram` | human-readable bytes |
| Context | `context_length` | thousands separator (e.g. "4,096") |

### Tags table columns

| Column | Source field | Formatting |
|--------|-------------|------------|
| Name | `name` | as-is |
| Model | `model` | as-is |
| Size | `size` | human-readable bytes |
| Parameters | `details.parameter_size` | as-is |
| Quantisation | `details.quantization_level` | as-is |

### Styling

Standard admin Catppuccin patterns: mono font, 11px, `text-white/60` headers,
`border-white/6` row borders, `bg-surface` background.
