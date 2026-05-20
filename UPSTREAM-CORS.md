# Upstream CORS & Browser-Direct-Eignung

**Erfasst:** 2026-05-18
**Methode:** CORS-Preflights via `curl -X OPTIONS` (empirisch) + Doku/SDK/Issue-Recherche
**Zweck:** Forschungsgrundlage für eine Client-Driven-Inferenz-Architektur (Browser spricht direkt mit Upstreams, ohne Backend-Proxy)

> Snapshot — CORS-Header und Auth-Modelle können sich ändern. Vor Implementierung neu probieren.

---

## Provider-Matrix

| Provider | CORS offen | Auth-Pfad ohne Key-Exposure | Browser-direct | Hauptbedingung |
|---|---|---|---|---|
| **OpenRouter** | Wildcard `*` | **OAuth PKCE** (offiziell SPA) | **JA — Gold-Standard** | Nutzer authentifiziert sich, App sieht den Key nie |
| **xAI** (Voice) | Wildcard `*` | **Ephemeral Tokens** (`/v1/realtime/client_secrets`) | **JA** | Backend mintet kurzlebigen Token (z.B. 300 s); Voice → WSS-Subprotokoll |
| **xAI** (Chat/Image) | Wildcard `*` | keine Ephemerals dokumentiert | **JA mit BYOK** | User-eigener Key im Browser |
| **Chutes** | offen + bewusste Header-Liste | **"Sign in with Chutes"** OAuth | **JA** | OAuth-Flow; alternativ scoped Keys via CLI |
| **Mistral** (Chat/STT/TTS) | Wildcard `*` | nur Bearer | **JA mit BYOK** | SDK Browser-first, kein `dangerouslyAllowBrowser`-Flag nötig |
| **Mistral Voxtral Realtime** | n/a (WSS) | nur Bearer | **JA mit BYOK** | WSS umgeht CORS, Auth in Sub-Protokoll |
| **nano-gpt** | Wildcard `*` | keine scoped Keys/OAuth | **NUR mit Key-Exposure** | Geduldet, nicht beworben |
| **Novita** | Wildcard `*` | Limits Account-weit | **NUR mit Key-Exposure** | — |
| **Tensorix** | offen (mit Credentials, reflektierte Origin) | Anbieter rät explizit ab | **NUR mit Key-Exposure** | Doku warnt aktiv |
| **Ollama self-hosted** | via `OLLAMA_ORIGINS` | via Reverse-Proxy (Caddy + Bearer + TLS) | **JA** | User-Aufwand: Proxy einrichten |
| **Ollama Cloud** | keine Header gesetzt | long-lived Keys | **NEIN** | Preflight scheitert; nur Backend-Proxy möglich |

---

## Drei Klassen

### 1. Gold (OAuth / Ephemeral)

Kein langlebiger Key landet je im Browser-Memory.

- **OpenRouter** — OAuth PKCE, offiziell für SPAs. Deckt durch Provider-Pass-Through auch Anthropic/OpenAI ab.
- **xAI Voice** — `POST /v1/realtime/client_secrets` mintet kurzlebige Tokens (TTL konfigurierbar). Genau das OpenAI-`client_secrets`-Muster.
- **Chutes** — "Sign in with Chutes" OAuth mit Scopes (`openid/profile/chutes:invoke`).

### 2. Silber (BYOK + offene CORS)

Funktioniert technisch, aber der Key liegt im Browser → XSS-Risiko trägt der User. Vertretbar wenn jeder seinen eigenen Key einträgt; disqualifiziert für Shared-Key-Betrieb.

- xAI Chat / Image
- Mistral (Chat, STT, TTS, Voxtral Realtime)
- nano-gpt
- Novita

### 3. Bronze / Sperrig

- **Ollama self-hosted** — geht, aber User muss Reverse-Proxy mit Bearer/Basic-Auth bauen
- **Tensorix** — Anbieter rät selbst von Browser-Use ab
- **Ollama Cloud** — einziger harter Blocker im Stack: keine CORS-Header, Preflight scheitert

---

## Architektur-Implikationen

- **Realistische Vision:** Pure Client-driven für den Großteil des Volumens machbar. OpenRouter allein deckt LLM-Text breit ab (inkl. der grossen Modelle). xAI deckt Voice + Image sauber ab.
- **Voice ist überraschend einfach:** WSS hat kein CORS-Problem, und xAI hat explizit Ephemerals. Mistral Voxtral läuft ebenfalls direkt aus dem Browser.
- **Wo ein minimaler Backend-Rest nötig bleibt:**
  - **Websearch:** Ollama Cloud blockt → entweder anderer Provider oder ein Mini-Proxy nur für `/api/web_search`
  - **Ephemeral-Token-Minting** für xAI Voice (einziger Server-Call pro Voice-Session)
  - Optional: **PKCE-Callback-URL** muss irgendwo gehostet sein (statisches Hosting reicht, kein Backend-Code)
- **NGO-Frage:** Wenn "Plattform bezahlt die Inferenz" → immer Backend-Proxy nötig. Wenn "Plattform, jeder bringt seinen Key" → Browser-direct ist die richtige Antwort, und **OpenRouter PKCE ist das saubere Eintrittsticket**.

---

## Quellen

### xAI
- [Grok Voice Agent API](https://docs.x.ai/docs/guides/voice/agent)
- [Ephemeral Tokens](https://docs.x.ai/developers/model-capabilities/audio/ephemeral-tokens)
- [Voice Agent API](https://docs.x.ai/developers/model-capabilities/audio/voice-agent)
- [Image Generation](https://docs.x.ai/developers/model-capabilities/images/generation)
- [@ai-sdk/xai on npm](https://www.npmjs.com/package/@ai-sdk/xai)
- [xai-cookbook voice-examples/agent/web](https://github.com/xai-org/xai-cookbook/tree/main/voice-examples/agent/web)

### OpenRouter
- [OAuth PKCE Guide](https://openrouter.ai/docs/guides/overview/auth/oauth)
- [API Authentication](https://openrouter.ai/docs/api/reference/authentication)
- [API Streaming](https://openrouter.ai/docs/api/reference/streaming)
- [TypeScript SDK](https://openrouter.ai/docs/sdks/typescript) / [GitHub](https://github.com/OpenRouterTeam/typescript-sdk)
- [Rate Limits & Scoped Keys](https://openrouter.ai/docs/api/reference/limits)

### Mistral
- [Mistral API Specs](https://docs.mistral.ai/api)
- [Mistral API Keys](https://docs.mistral.ai/admin/security-access/api-keys)
- [Speech to Text](https://docs.mistral.ai/studio-api/audio/speech_to_text)
- [Voxtral-Mini-4B-Realtime-2602 (Hugging Face)](https://huggingface.co/mistralai/Voxtral-Mini-4B-Realtime-2602)
- [mistralai/client-ts on GitHub](https://github.com/mistralai/client-ts)
- [@mistralai/mistralai on npm](https://www.npmjs.com/package/@mistralai/mistralai)
- [Security Advisories](https://docs.mistral.ai/resources/security-advisories) (Nov 2025 Supply-Chain-Issue → Version-Pinning)

### Kleinere Router
- nano-gpt: [Quickstart](https://docs.nano-gpt.com/quickstart), [Rate Limits](https://docs.nano-gpt.com/api-reference/miscellaneous/rate-limits)
- Novita: [API Reference](https://novita.ai/docs/api-reference/api-reference-overview), [Rate Limits](https://novita.ai/docs/guides/model-apis-rate-limits)
- Chutes: [Auth](https://chutes.ai/docs/getting-started/authentication), [Sign in with Chutes](https://chutes.ai/docs/sign-in-with-chutes/overview)
- Tensorix: [Overview](https://docs.tensorix.ai/api-reference/overview)

### Ollama
- [FAQ — OLLAMA_ORIGINS](https://docs.ollama.com/faq)
- [Auth Docs](https://docs.ollama.com/api/authentication)
- [Streaming Docs (NDJSON)](https://docs.ollama.com/api/streaming)
- [Web Search Blog](https://ollama.com/blog/web-search)
- [Issue #300 — Browser origins](https://github.com/ollama/ollama/issues/300)
- [Issue #4001 — Authorization header CORS](https://github.com/ollama/ollama/issues/4001)
- [Issue #7880 — CORS permissions UI](https://github.com/ollama/ollama/issues/7880)
- [Reverse-Proxy Pattern (Caddy/Nginx)](https://www.glukhov.org/llm-hosting/ollama/ollama-behind-reverse-proxy/)
- [kesor/ollama-proxy (Cloudflare Tunnel + Auth)](https://github.com/kesor/ollama-proxy)
