# Chatsune MCP Gateway — Implementation Specification

This document specifies the **chatsune-mcp-gateway**, a standalone Python service
that aggregates multiple MCP servers (stdio and HTTP) behind a single HTTP endpoint
speaking the standard MCP protocol (JSON-RPC over HTTP).

This is a separate project (own repository: `chatsune-mcp-gateway`).

---

## Purpose

Users run this gateway locally (or on a VPS) to expose their MCP servers to
Chatsune. The gateway handles:

- **stdio MCP servers** — spawns child processes, translates JSON-RPC over stdin/stdout
- **HTTP MCP servers** — proxies requests to remote MCP endpoints
- **Tool aggregation** — merges tools from all connected servers into one `tools/list` response
- **Unified HTTP endpoint** — Chatsune's frontend or backend talks to one URL per gateway

---

## Architecture

```
Chatsune (browser or backend)
    |
    |  HTTP (MCP JSON-RPC)
    v
+-----------------------------+
|   chatsune-mcp-gateway      |
|   (Python, single process)  |
|                             |
|   +--- Server Registry ---+ |
|   |                       | |
|   |  stdio: filesystem    | |
|   |  stdio: sqlite        | |
|   |  http:  remote-tools  | |
|   +-----------------------+ |
|                             |
|   +--- Tool Index --------+ |
|   |                       | |
|   |  tool_name -> server  | |
|   +-----------------------+ |
+-----------------------------+
    |           |           |
    v           v           v
  stdio       stdio       HTTP
  process     process     proxy
```

---

## Technology Stack

- **Python 3.12+** with **uv** for dependency management
- **FastAPI** or **Starlette** — lightweight HTTP server
- **asyncio** — subprocess management for stdio servers
- **httpx** — async HTTP client for proxying to HTTP MCP servers
- **PyYAML** — configuration parsing
- No database, no Redis, no external dependencies beyond the MCP servers themselves

---

## Configuration

Single YAML file, default path: `gateway.yaml` (override via `--config` CLI flag).

```yaml
# Gateway server settings
listen:
  host: "127.0.0.1"      # bind address
  port: 9100              # default port

# Optional authentication
# When set, all incoming requests must include: Authorization: Bearer <token>
auth_token: null          # string or null — null means no auth required

# MCP server definitions
servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/chris/docs"]
    env:                  # optional extra environment variables
      NODE_ENV: production

  - name: sqlite
    transport: stdio
    command: uvx
    args: ["mcp-server-sqlite", "--db", "/tmp/test.db"]

  - name: remote-tools
    transport: http
    url: "https://remote-mcp-server.example.com/mcp"
    api_key: "sk-remote-key"   # optional, sent as Bearer token to upstream
    timeout: 30                # HTTP timeout in seconds, default 30

  - name: weather
    transport: stdio
    command: python
    args: ["-m", "my_weather_mcp_server"]
```

### Server Definition Fields

| Field | Required | Transport | Description |
|-------|----------|-----------|-------------|
| `name` | yes | both | Unique identifier for this server within the gateway |
| `transport` | yes | both | `"stdio"` or `"http"` |
| `command` | yes | stdio | Path to executable to spawn |
| `args` | no | stdio | Command-line arguments (list of strings) |
| `env` | no | stdio | Extra environment variables (merged with gateway's env) |
| `url` | yes | http | Full URL of the remote MCP endpoint |
| `api_key` | no | http | Bearer token for upstream authentication |
| `timeout` | no | http | HTTP timeout in seconds (default: 30) |

### Configuration Validation (at startup)

- All server names must be unique
- stdio servers: `command` must be resolvable in PATH
- http servers: `url` must be a valid HTTP(S) URL
- Port must be in valid range (1024-65535 for non-root)
- Warn (but don't fail) if a server is unreachable at startup

---

## MCP Protocol — HTTP Transport

The gateway speaks standard **MCP JSON-RPC over HTTP**. All communication uses
`POST` to a single endpoint.

### Endpoint

```
POST /mcp
Content-Type: application/json
Authorization: Bearer <token>    # only if auth_token is configured
```

### Supported Methods

#### `tools/list`

Returns all tools from all connected servers, aggregated into one response.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "tools/list"
}
```

**Response:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [
      {
        "name": "read_file",
        "description": "Read the contents of a file at the specified path",
        "inputSchema": {
          "type": "object",
          "properties": {
            "path": {
              "type": "string",
              "description": "Absolute path to the file to read"
            }
          },
          "required": ["path"]
        },
        "_gateway_server": "filesystem"
      },
      {
        "name": "query",
        "description": "Execute a SQL query",
        "inputSchema": {
          "type": "object",
          "properties": {
            "sql": { "type": "string", "description": "SQL query to execute" }
          },
          "required": ["sql"]
        },
        "_gateway_server": "sqlite"
      }
    ]
  }
}
```

**Notes:**
- `_gateway_server` is a non-standard extension field that tells the client which
  server provides this tool. Chatsune does not use this field (it uses the namespace
  prefix instead), but it is useful for debugging.
- Tool names are returned as-is from the upstream server. **The gateway does NOT
  apply namespace prefixes** — that is the responsibility of Chatsune (the MCP host).
- If a server is unreachable, its tools are omitted from the response (no error).
  A `_errors` extension field lists unreachable servers.

**Response with partial failure:**
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "tools": [ ... ],
    "_errors": [
      { "server": "remote-tools", "error": "Connection refused" }
    ]
  }
}
```

#### `tools/call`

Calls a specific tool. The gateway routes to the correct server based on tool name.

**Request:**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "tools/call",
  "params": {
    "name": "read_file",
    "arguments": {
      "path": "/home/chris/example.txt"
    }
  }
}
```

**Response (success):**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "File contents here..."
      }
    ]
  }
}
```

**Response (tool error):**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "Error: file not found"
      }
    ],
    "isError": true
  }
}
```

**Response (routing error — unknown tool):**
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "error": {
    "code": -32601,
    "message": "Tool 'unknown_tool' not found in any connected server"
  }
}
```

### Tool Name Collision Handling

If multiple servers expose a tool with the same name, the gateway uses **first-match**
based on server order in the config file. A warning is logged at startup:

```
WARNING: Tool 'read_file' provided by both 'filesystem' and 'remote-tools'.
         Using 'filesystem' (first in config). Consider renaming in your MCP server.
```

The `tools/list` response includes the `_gateway_server` field so the client can
detect collisions if needed.

---

## Health Endpoint

```
GET /health
```

**Response:**
```json
{
  "status": "ok",
  "servers": [
    { "name": "filesystem", "transport": "stdio", "status": "running", "tools": 5 },
    { "name": "sqlite", "transport": "stdio", "status": "running", "tools": 3 },
    { "name": "remote-tools", "transport": "http", "status": "unreachable", "tools": 0 }
  ],
  "total_tools": 8
}
```

This endpoint does NOT require authentication (even if `auth_token` is set)
to allow simple monitoring and health checks.

---

## stdio Server Lifecycle

### Startup

1. Gateway reads config, validates server definitions
2. For each stdio server:
   a. Spawn subprocess via asyncio subprocess APIs
   b. Send MCP `initialize` handshake over stdin/stdout
   c. Send `tools/list` to discover available tools
   d. Build tool index: `tool_name -> server_name`
3. For each HTTP server:
   a. Send `tools/list` via HTTP
   b. Build tool index
4. Start HTTP server on configured `listen` address

### Process Management

- stdio processes are monitored — if a process exits unexpectedly, the gateway:
  - Logs the error
  - Removes the server's tools from the index
  - Attempts restart after 5 seconds (max 3 retries, then gives up)
  - A restart re-runs `tools/list` and updates the tool index
- Graceful shutdown (SIGTERM/SIGINT):
  - Stops accepting new requests
  - Sends shutdown to all stdio processes
  - Waits up to 5 seconds for processes to exit
  - Force-kills remaining processes

### stdio JSON-RPC Framing

MCP over stdio uses **newline-delimited JSON**. Each message is a single JSON
object followed by a newline. The gateway:

- Writes JSON-RPC requests to the subprocess's stdin
- Reads JSON-RPC responses from the subprocess's stdout
- Ignores stderr (but logs it for debugging)
- Maintains a pending request map (JSON-RPC `id` to `asyncio.Future`) for
  concurrent tool calls to the same server

---

## CLI Interface

```bash
# Start with default config (gateway.yaml in current directory)
chatsune-mcp-gateway

# Start with custom config
chatsune-mcp-gateway --config /path/to/gateway.yaml

# Start with custom port (overrides config)
chatsune-mcp-gateway --port 9200

# Validate config without starting
chatsune-mcp-gateway --validate

# Show version
chatsune-mcp-gateway --version
```

### Installation

```bash
# Via uv (recommended)
uv tool install chatsune-mcp-gateway

# Then run
chatsune-mcp-gateway --config gateway.yaml
```

---

## Logging

Structured JSON logging to stdout:

```json
{"ts": "2026-04-12T10:30:00Z", "level": "info", "msg": "Server started", "server": "filesystem", "transport": "stdio", "tools": 5}
{"ts": "2026-04-12T10:30:00Z", "level": "info", "msg": "Gateway listening", "host": "127.0.0.1", "port": 9100}
{"ts": "2026-04-12T10:30:05Z", "level": "warn", "msg": "Server unreachable", "server": "remote-tools", "error": "Connection refused"}
{"ts": "2026-04-12T10:30:10Z", "level": "info", "msg": "Tool called", "tool": "read_file", "server": "filesystem", "duration_ms": 42}
```

Log level configurable via `--log-level` (debug, info, warn, error). Default: info.

---

## Security Considerations

- **Bind to 127.0.0.1 by default** — only accessible locally
- If binding to 0.0.0.0 (for VPS use), `auth_token` should be set
- The gateway does NOT validate tool arguments — that is the MCP server's responsibility
- stdio processes inherit the gateway's user permissions — be aware of what file system
  access this grants
- HTTP proxy requests to upstream servers use the upstream's `api_key` if configured

---

## Docker Support

A Dockerfile and compose file should be provided for VPS deployment:

- Base image: `python:3.12-slim`
- Expose port 9100
- Mount config file and any directories that stdio servers need access to
- Note: stdio MCP servers that are npm packages or Python packages need their
  runtimes available in the container. Either use a multi-runtime base image
  or use HTTP transport between separate containers.

---

## Scope Boundaries

The gateway is intentionally minimal. It does NOT:

- Manage users or sessions (that is Chatsune's job)
- Apply namespace prefixes to tool names (that is Chatsune's job)
- Cache tool results
- Rate limit requests
- Provide a web UI (Chatsune's Tool Explorer serves this purpose)
- Support MCP resources or prompts (tools only, for now)

---

## Future Considerations (not in scope for v1)

- **SSE streaming** for long-running tools (v1 uses request/response only)
- **MCP resources and prompts** support
- **Dynamic server management** via API (add/remove servers without restart)
- **Tool result caching** with configurable TTL
- **WebSocket transport** as alternative to HTTP
