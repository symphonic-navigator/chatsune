# Background Jobs Hardening — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the background-job system before the open-source test release so that testers cannot burn through their Ollama Cloud usage through bugs, queue floods, stuck jobs, or runaway retries.

**Architecture:** Introduce a thin "safeguards" layer (`backend/modules/safeguards/`) that sits in front of every LLM call issued from a background job. The layer enforces per-user rate limits, per-user job-queue caps, a daily job-token budget, a global kill-switch, and a per-user×model×provider circuit-breaker. All state lives in Redis (no new DBMS). In parallel, fix concrete Critical/High bugs in the existing job system: heartbeat race conditions, cursor-reset in the periodic extraction loop, atomic journal writes, execution-token idempotency, token-length checks before consolidation, HTTP-stream cancellation on timeout with exponential backoff, a Redis-backed retry buffer for disconnect-triggered extractions, and a gutter-timeout for NDJSON parsing.

**Tech Stack:** Python 3.12, FastAPI, `redis.asyncio`, `motor`/PyMongo (MongoDB replica set with transactions), `pytest`/`pytest-asyncio`, `httpx.AsyncClient` (streaming).

**Source document:** `BACKGROUND-JOBS-DEBT.md` at repo root. Every finding referenced here (C-xxx, H-xxx, M-xxx, L-xxx, SG-xxx) maps to a numbered section there.

**Branch strategy:** Work directly on `master` (project convention per `CLAUDE.md`). Commit after every task.

---

## File Structure

### New files

- `backend/modules/safeguards/__init__.py` — public API: `check_job_preconditions()`, `record_job_tokens()`, `record_job_failure()`, `record_job_success()`, `is_emergency_stopped()`. Nothing else is importable.
- `backend/modules/safeguards/_rate_limiter.py` — per-user×provider rolling-window rate limit (Redis INCR + EXPIRE).
- `backend/modules/safeguards/_queue_cap.py` — per-user job-queue cap using a Redis sorted set. When the cap is exceeded, oldest queued job is evicted from its stream.
- `backend/modules/safeguards/_budget.py` — per-user daily job-token budget. Reads `JOB_DAILY_TOKEN_BUDGET` from env (default 5_000_000, 0 = disabled). Stores daily counters in Redis with TTL of 36 h.
- `backend/modules/safeguards/_circuit_breaker.py` — per-user×provider×model breaker. Closed → Open (after N failures in window) → Half-Open (one probe) → Closed/Open.
- `backend/modules/safeguards/_config.py` — reads all env vars with documented defaults.
- `tests/safeguards/__init__.py`
- `tests/safeguards/test_rate_limiter.py`
- `tests/safeguards/test_queue_cap.py`
- `tests/safeguards/test_budget.py`
- `tests/safeguards/test_circuit_breaker.py`
- `tests/safeguards/test_integration.py` — end-to-end check that `submit()` respects queue cap + kill-switch.

### Modified files (known touchpoints)

- `backend/jobs/_submit.py` — enforce queue-cap and kill-switch at submit time.
- `backend/jobs/_consumer.py` — enforce rate-limit + budget + circuit-breaker + kill-switch before handler dispatch; record success/failure after.
- `backend/jobs/handlers/_memory_extraction.py` — atomic transaction (C-004), execution-token (H-005), record token usage (SG-002).
- `backend/jobs/handlers/_memory_consolidation.py` — token-length check (H-001), atomic writes if any, execution-token, token usage recording.
- `backend/jobs/handlers/_title_generation.py` — execution-token, token usage recording.
- `backend/main.py` — `_periodic_extraction_loop` cursor reset on exception (C-003), extraction submit rate-limit.
- `backend/modules/chat/_orchestrator.py` — `asyncio.Lock` around heartbeat/cancel dicts (C-002), `_idle_extraction_tasks` lock (M-005, opportunistic), `trigger_disconnect_extraction` retry loop (H-003).
- `backend/ws/router.py` — no-longer-swallowing exception in disconnect extraction path (H-003).
- `backend/modules/llm/_adapters/_ollama_base.py` — gutter-timeout per chunk (H-004), ensure httpx stream closed on cancel (H-002).
- `backend/modules/llm/__init__.py` — expose a helper to count input tokens for a given model (H-001). If tokeniser access is non-trivial, use a byte-count heuristic documented in the code.
- `backend/jobs/_retry.py` — exponential backoff (H-002).
- `.env.example` — document every new env var.
- `README.md` — document the new env vars under a new "Safeguards" subsection.
- `BACKGROUND-JOBS-DEBT.md` — check off completed items after each task.

---

## Environment variables (all new)

All new env vars live in a dedicated "Safeguards" block in `.env.example` and `README.md`.

```
# Safeguards ---------------------------------------------------------
# Global kill-switch: when set to "true", every LLM call originating
# from a background job is rejected with UnrecoverableJobError.
# Can be flipped at runtime via env reload — no redeploy required.
OLLAMA_CLOUD_EMERGENCY_STOP=false

# Per-user rate limit for upstream LLM calls (background jobs only).
# Rolling window in seconds and max calls per window.
JOB_RATE_LIMIT_WINDOW_SECONDS=60
JOB_RATE_LIMIT_MAX_CALLS=50

# Per-user job queue cap. When exceeded, the oldest queued job is
# dropped (ZPOPMIN + XDEL from the stream) to make room for the new
# one. Set to 0 to disable.
JOB_QUEUE_CAP_PER_USER=10

# Daily token budget for background jobs (per user, UTC day).
# 0 disables the check. Default 5 M tokens/day.
JOB_DAILY_TOKEN_BUDGET=5000000

# Circuit breaker: N failures within WINDOW seconds open the breaker
# for OPEN_SECONDS. One probe request is allowed in half-open state.
JOB_CIRCUIT_FAILURE_THRESHOLD=5
JOB_CIRCUIT_WINDOW_SECONDS=300
JOB_CIRCUIT_OPEN_SECONDS=900
```

---

## Execution order rationale

Safeguards first — they are the "insurance policy" that protects us while the rest of the hardening lands. Each safeguard task is independently testable with fake Redis (fakeredis or a live test Redis — see existing `tests/conftest.py` for the project's convention). Bug fixes come after the safety net exists.

---

## Task 1 — Safeguard config module

**Files:**
- Create: `backend/modules/safeguards/__init__.py` (stub for now: `from ._config import SafeguardConfig`)
- Create: `backend/modules/safeguards/_config.py`
- Create: `tests/safeguards/__init__.py` (empty)
- Create: `tests/safeguards/test_config.py`

- [ ] **Step 1: Read existing config conventions**

  Read `backend/main.py` top-of-file and any existing `settings`/`config` module the project uses. Match the same pattern (env var reading, default values, type coercion). The goal is for `SafeguardConfig` to feel native.

- [ ] **Step 2: Write failing tests**

  In `tests/safeguards/test_config.py`, write tests that verify:
  1. Defaults are correct when env is empty.
  2. Each env var is read and coerced to the right type (int/bool).
  3. `JOB_QUEUE_CAP_PER_USER=0` disables the cap (`config.queue_cap_enabled is False`).
  4. `JOB_DAILY_TOKEN_BUDGET=0` disables the budget.
  5. `OLLAMA_CLOUD_EMERGENCY_STOP` accepts `true`/`false`/`1`/`0` case-insensitively.

  Use `monkeypatch.setenv` and a fresh `SafeguardConfig.from_env()` classmethod call per test.

- [ ] **Step 3: Run tests — expect failure**

  ```bash
  uv run pytest tests/safeguards/test_config.py -v
  ```
  Expected: `ModuleNotFoundError` or test failures.

- [ ] **Step 4: Implement `SafeguardConfig`**

  `backend/modules/safeguards/_config.py`:
  ```python
  """Configuration for the safeguards layer. All values are read from
  environment variables with sensible defaults. See README.md for
  documentation of each variable."""
  from __future__ import annotations

  import os
  from dataclasses import dataclass


  def _env_int(name: str, default: int) -> int:
      raw = os.environ.get(name)
      if raw is None or raw == "":
          return default
      return int(raw)


  def _env_bool(name: str, default: bool) -> bool:
      raw = os.environ.get(name)
      if raw is None:
          return default
      return raw.strip().lower() in {"1", "true", "yes", "on"}


  @dataclass(frozen=True)
  class SafeguardConfig:
      emergency_stop: bool
      rate_limit_window_seconds: int
      rate_limit_max_calls: int
      queue_cap_per_user: int
      daily_token_budget: int
      circuit_failure_threshold: int
      circuit_window_seconds: int
      circuit_open_seconds: int

      @classmethod
      def from_env(cls) -> "SafeguardConfig":
          return cls(
              emergency_stop=_env_bool("OLLAMA_CLOUD_EMERGENCY_STOP", False),
              rate_limit_window_seconds=_env_int("JOB_RATE_LIMIT_WINDOW_SECONDS", 60),
              rate_limit_max_calls=_env_int("JOB_RATE_LIMIT_MAX_CALLS", 50),
              queue_cap_per_user=_env_int("JOB_QUEUE_CAP_PER_USER", 10),
              daily_token_budget=_env_int("JOB_DAILY_TOKEN_BUDGET", 5_000_000),
              circuit_failure_threshold=_env_int("JOB_CIRCUIT_FAILURE_THRESHOLD", 5),
              circuit_window_seconds=_env_int("JOB_CIRCUIT_WINDOW_SECONDS", 300),
              circuit_open_seconds=_env_int("JOB_CIRCUIT_OPEN_SECONDS", 900),
          )

      @property
      def queue_cap_enabled(self) -> bool:
          return self.queue_cap_per_user > 0

      @property
      def budget_enabled(self) -> bool:
          return self.daily_token_budget > 0
  ```

- [ ] **Step 5: Run tests — expect pass**

  ```bash
  uv run pytest tests/safeguards/test_config.py -v
  ```
  All green.

- [ ] **Step 6: Commit**

  ```bash
  git add backend/modules/safeguards/ tests/safeguards/
  git commit -m "Add SafeguardConfig module for background-job safety net"
  ```

---

## Task 2 — Kill-switch (SG-003)

**Files:**
- Modify: `backend/modules/safeguards/__init__.py`
- Create: `tests/safeguards/test_kill_switch.py`

- [ ] **Step 1: Write failing tests**

  `tests/safeguards/test_kill_switch.py`:
  ```python
  from backend.modules.safeguards import is_emergency_stopped
  from backend.modules.safeguards._config import SafeguardConfig

  def test_kill_switch_off_by_default(monkeypatch):
      monkeypatch.delenv("OLLAMA_CLOUD_EMERGENCY_STOP", raising=False)
      assert is_emergency_stopped(SafeguardConfig.from_env()) is False

  def test_kill_switch_on(monkeypatch):
      monkeypatch.setenv("OLLAMA_CLOUD_EMERGENCY_STOP", "true")
      assert is_emergency_stopped(SafeguardConfig.from_env()) is True
  ```

- [ ] **Step 2: Run tests — expect import error**

  ```bash
  uv run pytest tests/safeguards/test_kill_switch.py -v
  ```

- [ ] **Step 3: Implement**

  Add to `backend/modules/safeguards/__init__.py`:
  ```python
  from ._config import SafeguardConfig

  def is_emergency_stopped(config: SafeguardConfig) -> bool:
      return config.emergency_stop

  __all__ = ["SafeguardConfig", "is_emergency_stopped"]
  ```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

  ```bash
  git add backend/modules/safeguards/__init__.py tests/safeguards/test_kill_switch.py
  git commit -m "Add kill-switch check to safeguards layer"
  ```

---

## Task 3 — Rate limiter (SG-001)

**Files:**
- Create: `backend/modules/safeguards/_rate_limiter.py`
- Create: `tests/safeguards/test_rate_limiter.py`
- Modify: `backend/modules/safeguards/__init__.py`

- [ ] **Step 1: Check existing test-redis convention**

  Open `tests/conftest.py` and `tests/test_job_submit.py`. See how they obtain a Redis client for tests (live test-redis vs fakeredis). **Use the same pattern** in every safeguards test. Do not introduce `fakeredis` if the project already uses a live test-redis fixture — and vice versa.

- [ ] **Step 2: Write failing tests**

  `tests/safeguards/test_rate_limiter.py` — test cases:
  1. First call within window: allowed, counter = 1.
  2. Fewer-than-max calls: all allowed.
  3. Exactly max calls: all allowed.
  4. One over max: raises `RateLimitExceededError`.
  5. Different users in the same window do not interfere.
  6. Different providers for the same user do not interfere.
  7. After window elapses (TTL expiry), counter resets (use short window like 1 s for the test and `asyncio.sleep(1.2)`).

  Use `SafeguardConfig(rate_limit_window_seconds=60, rate_limit_max_calls=3, ...)` via a helper that builds a minimal config. Do **not** call `from_env()` directly in tests that don't specifically test env reading.

- [ ] **Step 3: Run tests — expect failure**

- [ ] **Step 4: Implement**

  `backend/modules/safeguards/_rate_limiter.py`:
  ```python
  """Per-user × provider rolling-window rate limiter, backed by Redis."""
  from __future__ import annotations

  from redis.asyncio import Redis

  from ._config import SafeguardConfig


  class RateLimitExceededError(Exception):
      """Raised when a user has exceeded the per-provider call rate.

      The associated job should be failed with an UnrecoverableJobError
      at the call site so the retry loop does not feed the problem."""

      def __init__(self, user_id: str, provider_id: str, limit: int, window: int) -> None:
          self.user_id = user_id
          self.provider_id = provider_id
          self.limit = limit
          self.window = window
          super().__init__(
              f"Rate limit exceeded: {limit} calls per {window}s "
              f"for user={user_id} provider={provider_id}"
          )


  async def check_rate_limit(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      provider_id: str,
  ) -> None:
      """Raise RateLimitExceededError if the user has exhausted the
      configured per-provider call quota within the rolling window."""
      key = f"safeguard:ratelimit:{user_id}:{provider_id}"
      # INCR is atomic; EXPIRE is only applied on the first increment
      # to start the window. Subsequent calls inherit the TTL.
      async with redis.pipeline(transaction=True) as pipe:
          pipe.incr(key)
          pipe.expire(key, config.rate_limit_window_seconds, nx=True)
          results = await pipe.execute()
      current = int(results[0])
      if current > config.rate_limit_max_calls:
          raise RateLimitExceededError(
              user_id=user_id,
              provider_id=provider_id,
              limit=config.rate_limit_max_calls,
              window=config.rate_limit_window_seconds,
          )
  ```

  Export from `__init__.py`:
  ```python
  from ._rate_limiter import check_rate_limit, RateLimitExceededError
  ```
  and update `__all__`.

  **Note on `expire nx=True`:** requires `redis-py` ≥ 4.4. If the project's `pyproject.toml` pins an older version, fall back to: `GET` the TTL; if `-1`, call `EXPIRE`. Or use a Lua script. Pick whichever is already used elsewhere in the codebase (search for `expire(` in `backend/` first).

- [ ] **Step 5: Run tests — expect pass**

- [ ] **Step 6: Commit**

---

## Task 4 — Queue cap (C-001 new design)

**Files:**
- Create: `backend/modules/safeguards/_queue_cap.py`
- Create: `tests/safeguards/test_queue_cap.py`
- Modify: `backend/modules/safeguards/__init__.py`

**Design recap:** A Redis sorted set `safeguard:queue:{user_id}` is maintained alongside the Redis Stream. Members are stream message IDs; score is the submission timestamp (ms). On `enforce_queue_cap()`:
1. `ZADD` the new stream ID.
2. `ZCARD` — if ≤ cap, return (no eviction).
3. If > cap, `ZPOPMIN` the overflow count; for each popped stream ID, call `XDEL` on the stream and publish a `JobEvictedEvent` (best-effort, fire-and-forget).

- [ ] **Step 1: Read how the project currently submits jobs**

  Read `backend/jobs/_submit.py` in full. Identify:
  - The exact Redis stream key for jobs.
  - The return type of `xadd()` (bytes vs str — normalise to str).
  - Where `user_id` is available at submit time.
  - What the existing `JobEntry` / `JobEnvelope` looks like.

- [ ] **Step 2: Write failing tests**

  `tests/safeguards/test_queue_cap.py`:
  1. Submitting `cap` jobs — none are evicted.
  2. Submitting `cap + 1` — oldest is evicted, `XDEL` called once.
  3. Submitting `cap + 3` at once — three oldest evicted.
  4. Cap = 0 → disabled, never evicts regardless of size.
  5. Two different users with the cap each — independent.
  6. Eviction returns the list of evicted stream IDs so callers can log.

- [ ] **Step 3: Implement**

  `backend/modules/safeguards/_queue_cap.py`:
  ```python
  """Per-user cap on pending background jobs. Enforced at submit time.

  When a user exceeds the cap, the oldest queued job is evicted from the
  Redis Stream (XDEL). This protects downstream handlers from queue-flood
  bugs without rejecting new work — the most recent user intent wins."""
  from __future__ import annotations

  from redis.asyncio import Redis

  from ._config import SafeguardConfig


  def _queue_key(user_id: str) -> str:
      return f"safeguard:queue:{user_id}"


  async def enforce_queue_cap(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      stream_key: str,
      new_message_id: str,
      now_ms: int,
  ) -> list[str]:
      """Register the new job in the per-user queue set, then evict any
      overflow. Returns the list of stream IDs that were evicted (possibly
      empty). Caller is responsible for logging the eviction."""
      if not config.queue_cap_enabled:
          return []

      key = _queue_key(user_id)
      await redis.zadd(key, {new_message_id: now_ms})
      # Keep the sorted set from growing forever even if XDEL fails.
      await redis.expire(key, 86400)

      overflow = await redis.zcard(key) - config.queue_cap_per_user
      if overflow <= 0:
          return []

      evicted: list[str] = []
      for _ in range(overflow):
          popped = await redis.zpopmin(key, count=1)
          if not popped:
              break
          msg_id_bytes, _score = popped[0]
          msg_id = msg_id_bytes.decode() if isinstance(msg_id_bytes, bytes) else msg_id_bytes
          evicted.append(msg_id)
          try:
              await redis.xdel(stream_key, msg_id)
          except Exception:
              # Best-effort — the message may already have been consumed.
              # Leave the book-keeping consistent with the sorted set.
              pass
      return evicted


  async def acknowledge_job_done(
      redis: Redis,
      user_id: str,
      message_id: str,
  ) -> None:
      """Remove a completed job from the per-user queue set."""
      await redis.zrem(_queue_key(user_id), message_id)
  ```

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

---

## Task 5 — Daily token budget (SG-002)

**Files:**
- Create: `backend/modules/safeguards/_budget.py`
- Create: `tests/safeguards/test_budget.py`
- Modify: `backend/modules/safeguards/__init__.py`

- [ ] **Step 1: Write failing tests**

  Cover:
  1. Budget disabled (`daily_token_budget=0`) → `check_budget()` always passes, `record_tokens()` is a no-op.
  2. `check_budget(tokens=1000)` when 0 consumed, budget=5_000_000 → passes.
  3. `record_tokens(1000)` then `check_budget(1)` returns quota remaining of 4_999_999.
  4. `record_tokens(5_000_001)` then `check_budget(1)` → raises `BudgetExceededError`.
  5. Different users independent.
  6. Key has `~36h` TTL so the day boundary is not a silent amnesia — pick the UTC date string as part of the key: `safeguard:budget:{user_id}:{YYYY-MM-DD}`.
  7. `check_budget(tokens_to_reserve=N)` raises if `(current + N) > budget`.

- [ ] **Step 2: Implement**

  `backend/modules/safeguards/_budget.py`:
  ```python
  """Daily token budget for background jobs. Per user, UTC day.

  This does NOT cap the user's own interactive LLM usage — testers
  bring their own API keys and we stay out of that. This exists only
  to bound what the *server* spends on their behalf via automated
  jobs (extraction, consolidation, title generation). It protects
  users from bugs in our own code, not from themselves."""
  from __future__ import annotations

  from datetime import datetime, timezone

  from redis.asyncio import Redis

  from ._config import SafeguardConfig


  class BudgetExceededError(Exception):
      def __init__(self, user_id: str, spent: int, budget: int) -> None:
          self.user_id = user_id
          self.spent = spent
          self.budget = budget
          super().__init__(
              f"Daily job token budget exceeded: user={user_id} "
              f"spent={spent} budget={budget}"
          )


  def _key(user_id: str) -> str:
      today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
      return f"safeguard:budget:{user_id}:{today}"


  async def check_budget(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      tokens_to_reserve: int = 0,
  ) -> None:
      if not config.budget_enabled:
          return
      raw = await redis.get(_key(user_id))
      spent = int(raw) if raw else 0
      if spent + tokens_to_reserve > config.daily_token_budget:
          raise BudgetExceededError(user_id, spent, config.daily_token_budget)


  async def record_tokens(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      tokens: int,
  ) -> None:
      if not config.budget_enabled or tokens <= 0:
          return
      key = _key(user_id)
      async with redis.pipeline(transaction=True) as pipe:
          pipe.incrby(key, tokens)
          pipe.expire(key, 36 * 3600, nx=True)
          await pipe.execute()
  ```

- [ ] **Step 3: Run tests — expect pass**

- [ ] **Step 4: Commit**

---

## Task 6 — Circuit breaker (SG-005)

**Files:**
- Create: `backend/modules/safeguards/_circuit_breaker.py`
- Create: `tests/safeguards/test_circuit_breaker.py`
- Modify: `backend/modules/safeguards/__init__.py`

**Design:** Three states stored in a single Redis key `safeguard:cb:{user_id}:{provider_id}:{model_slug}` holding a JSON blob `{"state": "open|half_open|closed", "failures": N, "open_until": epoch_ms}`. Simpler alternative: two keys — a failure-counter key with window TTL, and an "open" marker key with open TTL. **Pick the two-key variant — simpler, atomic, no JSON.**

- [ ] **Step 1: Write failing tests**

  Cover:
  1. Closed by default → `check()` passes.
  2. `record_failure()` N-1 times → still closed.
  3. N-th failure → breaker opens; next `check()` raises `CircuitOpenError`.
  4. After `open_seconds`, breaker half-opens → next `check()` passes (probe allowed).
  5. In half-open state, a second concurrent `check()` is blocked (use an `open:half_probe_in_flight` marker with a short TTL, e.g. 60 s).
  6. Probe succeeds → `record_success()` resets everything.
  7. Probe fails → `record_failure()` re-opens for another `open_seconds`.
  8. Scoping: different `user/provider/model` tuples do not interfere.
  9. `record_success()` in closed state clears the failure counter.

- [ ] **Step 2: Implement**

  `backend/modules/safeguards/_circuit_breaker.py`:
  ```python
  """Per user × provider × model circuit breaker.

  Why per-model and not just per-provider: Ollama Cloud routes by model
  and a flakey llama3.2 should not take down qwen for the same user."""
  from __future__ import annotations

  from redis.asyncio import Redis

  from ._config import SafeguardConfig


  class CircuitOpenError(Exception):
      def __init__(self, user_id: str, provider_id: str, model_slug: str) -> None:
          self.user_id = user_id
          self.provider_id = provider_id
          self.model_slug = model_slug
          super().__init__(
              f"Circuit open: user={user_id} provider={provider_id} "
              f"model={model_slug}"
          )


  def _fail_key(u: str, p: str, m: str) -> str:
      return f"safeguard:cb:fail:{u}:{p}:{m}"


  def _open_key(u: str, p: str, m: str) -> str:
      return f"safeguard:cb:open:{u}:{p}:{m}"


  def _probe_key(u: str, p: str, m: str) -> str:
      return f"safeguard:cb:probe:{u}:{p}:{m}"


  async def check_circuit(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      provider_id: str,
      model_slug: str,
  ) -> None:
      """Raise CircuitOpenError if the breaker is open and no probe is
      currently allowed. If the breaker is half-open, this call claims
      the probe slot and returns."""
      open_exists = await redis.exists(_open_key(user_id, provider_id, model_slug))
      if not open_exists:
          return
      # Breaker is open. Try to claim the half-open probe slot.
      claimed = await redis.set(
          _probe_key(user_id, provider_id, model_slug),
          "1",
          nx=True,
          ex=60,
      )
      if not claimed:
          raise CircuitOpenError(user_id, provider_id, model_slug)
      # Probe allowed — fall through.


  async def record_failure(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      provider_id: str,
      model_slug: str,
  ) -> None:
      fkey = _fail_key(user_id, provider_id, model_slug)
      async with redis.pipeline(transaction=True) as pipe:
          pipe.incr(fkey)
          pipe.expire(fkey, config.circuit_window_seconds, nx=True)
          results = await pipe.execute()
      failures = int(results[0])
      if failures >= config.circuit_failure_threshold:
          await redis.set(
              _open_key(user_id, provider_id, model_slug),
              "1",
              ex=config.circuit_open_seconds,
          )
          # Drop the probe marker so the next check-after-open can claim it.
          await redis.delete(_probe_key(user_id, provider_id, model_slug))


  async def record_success(
      redis: Redis,
      config: SafeguardConfig,
      user_id: str,
      provider_id: str,
      model_slug: str,
  ) -> None:
      async with redis.pipeline(transaction=True) as pipe:
          pipe.delete(_fail_key(user_id, provider_id, model_slug))
          pipe.delete(_open_key(user_id, provider_id, model_slug))
          pipe.delete(_probe_key(user_id, provider_id, model_slug))
          await pipe.execute()
  ```

- [ ] **Step 3: Run tests — expect pass**

- [ ] **Step 4: Commit**

---

## Task 7 — Safeguard integration: `check_job_preconditions` + recording hooks

**Files:**
- Modify: `backend/modules/safeguards/__init__.py`
- Create: `tests/safeguards/test_integration.py`

- [ ] **Step 1: Public-API design**

  Add three high-level functions to `__init__.py`:
  ```python
  async def check_job_preconditions(
      redis: Redis,
      config: SafeguardConfig,
      *,
      user_id: str,
      provider_id: str,
      model_slug: str,
      estimated_input_tokens: int,
  ) -> None:
      """Call before dispatching a background-job LLM request. Raises:
      - EmergencyStoppedError (kill-switch on)
      - RateLimitExceededError
      - BudgetExceededError
      - CircuitOpenError
      Any of these should be wrapped in UnrecoverableJobError by the caller."""

  async def record_job_success(
      redis: Redis,
      config: SafeguardConfig,
      *,
      user_id: str,
      provider_id: str,
      model_slug: str,
      tokens_spent: int,
  ) -> None: ...

  async def record_job_failure(
      redis: Redis,
      config: SafeguardConfig,
      *,
      user_id: str,
      provider_id: str,
      model_slug: str,
  ) -> None: ...
  ```

  Also add `EmergencyStoppedError` as an exception class in `__init__.py`.

- [ ] **Step 2: Write integration tests**

  `tests/safeguards/test_integration.py`:
  - Kill-switch on → `check_job_preconditions` raises `EmergencyStoppedError`.
  - Rate-limit hit → raises `RateLimitExceededError`.
  - Budget hit → raises `BudgetExceededError`.
  - Circuit open → raises `CircuitOpenError`.
  - Happy path → returns cleanly.
  - `record_job_success` clears the circuit failures and records tokens.
  - `record_job_failure` increments the breaker.

- [ ] **Step 3: Implement**

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

---

## Task 8 — Wire safeguards into `_submit.py` (kill-switch + queue cap)

**Files:**
- Modify: `backend/jobs/_submit.py`
- Modify: `tests/test_job_submit.py` (or add a new `test_job_submit_safeguards.py`)

- [ ] **Step 1: Read `_submit.py` fully**

  Understand where `xadd` happens, what objects are in scope (Redis client, `JobEntry`, `user_id`), and how errors are surfaced to callers today.

- [ ] **Step 2: Write failing tests**

  New tests in `tests/test_job_submit_safeguards.py`:
  1. Submitting with `OLLAMA_CLOUD_EMERGENCY_STOP=true` raises `EmergencyStoppedError` (or whatever the project wraps it in) and does **not** call `xadd`.
  2. Submitting the 11th job for a user with cap=10 evicts the oldest (check `XDEL` was called, check the newly submitted job's ID is in the stream).
  3. Kill-switch off + under cap → normal behaviour unchanged.

- [ ] **Step 3: Implement**

  In `_submit.py`, after validating the envelope but before `xadd`:
  ```python
  from backend.modules.safeguards import (
      SafeguardConfig,
      is_emergency_stopped,
      EmergencyStoppedError,
  )
  from backend.modules.safeguards._queue_cap import enforce_queue_cap

  # ...

  config = SafeguardConfig.from_env()
  if is_emergency_stopped(config):
      raise EmergencyStoppedError(
          "Background-job submission rejected: emergency stop is active"
      )

  msg_id = await redis.xadd(stream_key, payload)
  now_ms = int(time.time() * 1000)
  msg_id_str = msg_id.decode() if isinstance(msg_id, bytes) else msg_id
  evicted = await enforce_queue_cap(
      redis, config, user_id=user_id, stream_key=stream_key,
      new_message_id=msg_id_str, now_ms=now_ms,
  )
  if evicted:
      log.warning(
          "job.queue_cap.evicted user=%s count=%d ids=%s",
          user_id, len(evicted), evicted,
      )
  ```

  If the logger is not yet imported, use whatever logging pattern the file already uses.

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

---

## Task 9 — Wire safeguards into `_consumer.py`

**Files:**
- Modify: `backend/jobs/_consumer.py`
- Add tests alongside existing `tests/test_job_consumer.py`

- [ ] **Step 1: Read `_consumer.py` and understand where `provider_id`/`model_slug` become available**

  These come from the `JobEntry.model_unique_id` (format `provider_id:model_slug` per INS-004). Parse that once per job.

- [ ] **Step 2: Add safeguards call before handler dispatch**

  Just before the `asyncio.timeout() → handler(...)` block:
  ```python
  from backend.modules.safeguards import (
      SafeguardConfig,
      check_job_preconditions,
      record_job_success,
      record_job_failure,
      EmergencyStoppedError,
      RateLimitExceededError,
      BudgetExceededError,
      CircuitOpenError,
  )
  from backend.modules.safeguards._queue_cap import acknowledge_job_done
  from backend.jobs._errors import UnrecoverableJobError

  config = SafeguardConfig.from_env()
  provider_id, _, model_slug = job.model_unique_id.partition(":")

  try:
      await check_job_preconditions(
          redis, config,
          user_id=job.user_id,
          provider_id=provider_id,
          model_slug=model_slug,
          estimated_input_tokens=0,  # refined in H-001 task
      )
  except (EmergencyStoppedError, RateLimitExceededError,
          BudgetExceededError, CircuitOpenError) as exc:
      raise UnrecoverableJobError(str(exc)) from exc
  ```

  Wrap the handler call in a try/except so failures are reported to the circuit breaker:
  ```python
  try:
      await config_obj.handler(...)
  except Exception:
      await record_job_failure(
          redis, config,
          user_id=job.user_id,
          provider_id=provider_id,
          model_slug=model_slug,
      )
      raise
  else:
      # Handlers report their own token usage via record_job_tokens.
      # Success here only clears the breaker.
      await record_job_success(
          redis, config,
          user_id=job.user_id,
          provider_id=provider_id,
          model_slug=model_slug,
          tokens_spent=0,
      )
  finally:
      await acknowledge_job_done(redis, job.user_id, message_id)
  ```

- [ ] **Step 3: Add tests**

  Verify that when the safeguards raise, the consumer marks the job as unrecoverable (no retry) and acks it.

- [ ] **Step 4: Run tests — expect pass**

- [ ] **Step 5: Commit**

---

## Task 10 — Heartbeat lock (C-002)

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py`
- Add: regression test in `tests/test_inference_runner.py` or a new file `tests/test_heartbeat_watchdog.py`

- [ ] **Step 1: Read `_orchestrator.py` around lines 330–430**

  Locate `_last_heartbeat`, `_cancel_user_ids`, `_cancel_events`, `_heartbeat_watchdogs`, `record_heartbeat`, `_heartbeat_watchdog`, `cancel_all_for_user`, and every mutation of these four dicts.

- [ ] **Step 2: Introduce a module-level lock**

  At the top where those dicts are declared, add:
  ```python
  import asyncio
  _heartbeat_lock = asyncio.Lock()
  ```

- [ ] **Step 3: Wrap every mutation**

  For every read-then-mutate sequence on those dicts, use `async with _heartbeat_lock:`. For pure reads followed by independent async work, still take the lock for the read itself to get a consistent snapshot, then release before awaiting anything else.

  Specifically:
  - `record_heartbeat` — acquire lock for the full check-and-set.
  - `cancel_all_for_user` — acquire lock; snapshot the list of correlation_ids to cancel; release lock; then `event.set()` outside the lock (setting an `asyncio.Event` is synchronous and safe).
  - `_heartbeat_watchdog` loop body — acquire lock to read `_last_heartbeat`, release, then compare and potentially re-acquire to mutate.
  - Finally-block cleanup — acquire lock for each `pop()`.
  - Watchdog task creation/teardown — acquire lock when mutating `_heartbeat_watchdogs`, and on teardown cancel the task (outside the lock) before popping it.

- [ ] **Step 4: Add a regression test**

  A test that spawns a fake heartbeat + disconnect race and asserts:
  - `KeyError` is never raised.
  - After disconnect, the watchdog task is cancelled.
  - `_last_heartbeat` / `_cancel_events` / `_heartbeat_watchdogs` are all empty for that correlation_id at the end.

  If a deterministic race is too hard, run the sequence 200 times in a loop inside the test.

- [ ] **Step 5: Verify build**

  ```bash
  uv run python -m py_compile backend/modules/chat/_orchestrator.py
  uv run pytest tests/test_inference_runner.py tests/test_heartbeat_watchdog.py -v
  ```

- [ ] **Step 6: Commit**

  ```
  Add asyncio.Lock around heartbeat/cancel dicts to fix race condition
  ```

---

## Task 11 — Cursor reset in periodic extraction loop (C-003)

**Files:**
- Modify: `backend/main.py` (the `_periodic_extraction_loop` around lines 272–380)

- [ ] **Step 1: Read the full loop**

- [ ] **Step 2: Fix the cursor handling**

  Refactor to:
  ```python
  async def _periodic_extraction_loop() -> None:
      while True:
          try:
              cursor = 0
              while True:
                  cursor, keys = await ext_redis.scan(
                      cursor=cursor, match="memory:extraction:*", count=100,
                  )
                  await _process_extraction_keys(keys)
                  if cursor == 0:
                      break
          except Exception:
              log.exception("periodic_extraction_loop: scan failed, resetting cursor")
              # Brief backoff so we do not hot-loop on a broken Redis.
              await asyncio.sleep(5)
          await asyncio.sleep(LOOP_INTERVAL_SECONDS)
  ```

  The key change: on exception, we break out of the inner `while True`, sleep briefly, and restart the scan from cursor 0 on the next iteration. No stale cursor carries over.

- [ ] **Step 3: Add a per-user submit rate-limit inside `_process_extraction_keys`**

  A simple Redis-backed guard: `safeguard:extraction_submit:{user_id}` with `SET NX EX 300`. If the key already exists, skip the submit for this user on this cycle.

- [ ] **Step 4: Verify**

  ```bash
  uv run python -m py_compile backend/main.py
  ```

- [ ] **Step 5: Commit**

---

## Task 12 — Atomic extraction writes + execution token (C-004 + H-005)

**Files:**
- Modify: `backend/jobs/handlers/_memory_extraction.py`
- Modify: `backend/jobs/_models.py` (add `execution_token: str` to `JobEntry`, generated in `_submit.py`)
- Modify: `backend/jobs/_submit.py` (generate token via `uuid.uuid4().hex`)
- Modify: `backend/jobs/handlers/_memory_consolidation.py` (same execution-token pattern)
- Modify: `backend/jobs/handlers/_title_generation.py` (same)

- [ ] **Step 1: Read the three handlers and `_models.py`**

- [ ] **Step 2: Add `execution_token` field**

  In `JobEntry`: `execution_token: str` (required, populated at submit time).

- [ ] **Step 3: Idempotency guard**

  At the very top of each handler:
  ```python
  token_key = f"job:executed:{job.execution_token}"
  already = await redis.set(token_key, "1", nx=True, ex=48 * 3600)
  if already is None:
      log.info("job.duplicate_skip token=%s", job.execution_token)
      return
  ```

  This uses `SET NX` as a one-shot "have we already run this job instance?" marker. 48 h TTL covers any PEL-replay scenario.

- [ ] **Step 4: Atomic journal writes in `_memory_extraction.py`**

  Read the current write sequence. Wrap `create_journal_entry(...)` for all entries **and** `mark_messages_extracted(message_ids)` inside a single MongoDB transaction:
  ```python
  async with await mongo_client.start_session() as session:
      async with session.start_transaction():
          entry_ids = []
          for entry_data in deduped_entries:
              eid = await repo.create_journal_entry(..., session=session)
              entry_ids.append(eid)
          if message_ids:
              await mark_messages_extracted(message_ids, session=session)
  # Events published AFTER the transaction commits, never before.
  for eid in entry_ids:
      await event_bus.publish(Topics.MEMORY_ENTRY_CREATED, ...)
  ```

  **Verify** that `repo.create_journal_entry` and `mark_messages_extracted` accept a `session=` kwarg. If not, add that kwarg first (they will pass it through to the underlying motor calls — see other repositories in the codebase for the pattern).

- [ ] **Step 5: Tests**

  - Execution-token guard: simulate a replayed job (same token) and assert the handler returns early, no DB calls made.
  - Transaction atomicity: inject a failure between `create_journal_entry` and `mark_messages_extracted`. Verify that neither side effect is visible after the failure.

- [ ] **Step 6: Commit**

---

## Task 13 — Token-length check before consolidation (H-001)

**Files:**
- Modify: `backend/jobs/handlers/_memory_consolidation.py`
- Create: `backend/modules/llm/_token_estimate.py`
- Add: `tests/llm/test_token_estimate.py`

- [ ] **Step 1: Decide on estimation strategy**

  A proper tokeniser per model is nontrivial. For safety, a conservative heuristic is sufficient:
  ```python
  def estimate_tokens(text: str) -> int:
      """Conservative upper-bound estimate: 1 token per 3 characters.
      Real tokenisers average 1 token per ~4 characters for English.
      We deliberately over-estimate so that the guard trips early."""
      return max(1, len(text) // 3)
  ```

  Also expose `context_window_for(provider_id: str, model_slug: str) -> int`. Look for an existing context-window lookup in the project first (`grep -r "context_window" backend/`). If one exists, use it. If not, return a safe default of 8192 and let model-specific overrides be added later.

- [ ] **Step 2: Enforce in the consolidation handler**

  ```python
  from backend.modules.llm._token_estimate import estimate_tokens, context_window_for

  system_prompt = build_consolidation_prompt(existing_body, entries_for_prompt)
  estimated = estimate_tokens(system_prompt)
  window = context_window_for(provider_id, model_slug)
  if estimated > window * 0.7:
      raise UnrecoverableJobError(
          f"Consolidation input too large: ~{estimated} tokens "
          f"(>70% of {window} context window). Skipping to avoid waste."
      )
  ```

- [ ] **Step 3: Truncate existing_body when too large**

  Before the check above, if `estimate_tokens(existing_body) > window * 0.5`, truncate the body to the last `window * 0.4 * 3` characters and prepend `"[... earlier memory truncated to fit context window ...]\n"`. Document this in a comment.

- [ ] **Step 4: Tests**

  - Small input → passes.
  - Massive body → truncated, then passes.
  - Massive body + massive entries → `UnrecoverableJobError`.
  - The token estimate function is also unit-tested.

- [ ] **Step 5: Commit**

---

## Task 14 — HTTP stream cancel + exponential backoff (H-002)

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_base.py`
- Modify: `backend/jobs/_retry.py`

- [ ] **Step 1: Read `_ollama_base.py`**

  Find the streaming section (`aiter_lines()` around lines 180–216). Determine whether the `httpx.AsyncClient`/`Response` context manager is entered with `async with`. It should be — so `asyncio.CancelledError` will propagate through and close the underlying socket automatically.

- [ ] **Step 2: Guarantee the stream is closed on cancel**

  If the current code uses `async with client.stream(...) as resp:` — good, cancellation will close it. If it uses a manually-managed response, wrap it in a `try/finally` that calls `await resp.aclose()`.

  Add an explicit `except asyncio.CancelledError:` branch that logs the cancellation with `user_id`, `model`, and `correlation_id` at WARNING level, then re-raises. This gives us the Cost-Tracking breadcrumb the analysis asked for.

- [ ] **Step 3: Exponential backoff in `_retry.py`**

  Read the current retry-delay logic. Replace the fixed `retry_delay_seconds` with:
  ```python
  def compute_backoff(attempt: int, base: int = 15, cap: int = 300) -> int:
      # 1 -> 15s, 2 -> 30s, 3 -> 60s, 4 -> 120s, 5 -> 240s, then capped
      return min(cap, base * (2 ** (attempt - 1)))
  ```
  Wire it into whatever the consumer currently reads to schedule the next retry attempt.

- [ ] **Step 4: Tests**

  `tests/test_retry_backoff.py` — unit tests for `compute_backoff` covering attempts 1–6.

  In `tests/test_job_consumer.py`, add a test that a handler raising on attempt 2 schedules the retry with 30 s delay (or whatever method the project uses to expose this — likely via the retry hash).

- [ ] **Step 5: Commit**

---

## Task 15 — Redis-backed disconnect-extraction retry buffer (H-003)

**Files:**
- Modify: `backend/modules/chat/_orchestrator.py` (`trigger_disconnect_extraction`)
- Modify: `backend/ws/router.py` (stop swallowing the exception silently)
- Modify: `backend/main.py` (add a periodic recovery loop that drains the retry buffer)

- [ ] **Step 1: Design**

  Sorted set `jobs:disconnect_retry:{user_id}` with score=`attempt_count`, members=JSON-encoded submit payloads. Recovery loop runs every 60 s, for each key `ZRANGE 0 -1 WITHSCORES`, tries `submit()` for each, on success `ZREM`, on failure `ZINCRBY` (max 5 attempts before dead-lettering to a `dead` key).

- [ ] **Step 2: `trigger_disconnect_extraction` retry loop**

  Replace the silent `submit()` call with:
  ```python
  async def trigger_disconnect_extraction(user_id: str) -> None:
      payload = _build_extraction_payload(user_id)
      attempts = 0
      delays = [0.1, 0.5, 2.0]
      last_exc: Exception | None = None
      for delay in delays:
          try:
              await asyncio.sleep(delay)
              await submit(payload)
              return
          except Exception as exc:
              attempts += 1
              last_exc = exc
      log.error(
          "trigger_disconnect_extraction: submit failed after %d attempts, buffering",
          attempts, exc_info=last_exc,
      )
      # Buffer in Redis for the recovery loop to pick up.
      await redis.zadd(
          f"jobs:disconnect_retry:{user_id}",
          {json.dumps(payload): 0},
      )
  ```

- [ ] **Step 3: Router — stop swallowing**

  The existing silent `try/except` block in `backend/ws/router.py` finally: re-raise? No — still catch, but **log at ERROR** with `exc_info=True`. The buffering logic above guarantees the data is safe.

- [ ] **Step 4: Recovery loop in `main.py`**

  New background task `_disconnect_retry_recovery_loop()`, scheduled alongside the other periodic loops in the app lifespan. Every 60 s it scans `jobs:disconnect_retry:*`, re-tries each payload, removes successes, increments failure scores, dead-letters after 5.

- [ ] **Step 5: Tests**

  Unit test `trigger_disconnect_extraction` with a mocked `submit` that fails 3 times, verifying the payload lands in the retry zset.

- [ ] **Step 6: Commit**

---

## Task 16 — NDJSON gutter-timeout (H-004)

**Files:**
- Modify: `backend/modules/llm/_adapters/_ollama_base.py`

- [ ] **Step 1: Identify the `async for line in resp.aiter_lines()` block**

- [ ] **Step 2: Add a gutter-timeout around each line fetch**

  ```python
  GUTTER_TIMEOUT = 30.0  # no new chunk for 30s → abort and yield StreamDone

  stream_iter = resp.aiter_lines().__aiter__()
  while True:
      try:
          line = await asyncio.wait_for(stream_iter.__anext__(), timeout=GUTTER_TIMEOUT)
      except asyncio.TimeoutError:
          log.warning(
              "ollama_base: gutter timeout reached, aborting stream user=%s model=%s",
              user_id, model,
          )
          if not seen_done:
              yield StreamDone(reason="gutter_timeout")
          break
      except StopAsyncIteration:
          break

      # ... existing line processing ...
  ```

  The existing `seen_done` fallback after the loop stays as a belt-and-braces.

- [ ] **Step 3: Tests**

  `tests/test_ollama_cloud_streaming.py` — mock an `aiter_lines()` that yields one chunk then hangs forever, assert that `StreamDone` is yielded within ~`GUTTER_TIMEOUT + epsilon`. Use a shorter gutter for the test via a module-level constant override or dependency injection.

- [ ] **Step 4: Commit**

---

## Task 17 — Record token usage from each handler (connects SG-002 to reality)

**Files:**
- Modify: each of the three job handlers to call `record_tokens` after a successful LLM call.

- [ ] **Step 1: Read how each handler currently inspects the stream result**

  Look for `StreamDone` or a total-tokens field on the adapter events. If the adapter does not report token usage, fall back to `estimate_tokens(full_input) + estimate_tokens(full_output)`.

- [ ] **Step 2: Add recording**

  Right after the LLM call completes successfully (before the journal writes / event publishes):
  ```python
  from backend.modules.safeguards._budget import record_tokens
  await record_tokens(
      redis, SafeguardConfig.from_env(),
      user_id=job.user_id,
      tokens=prompt_tokens + completion_tokens,
  )
  ```

- [ ] **Step 3: Call `check_budget` right before the call**

  Same place:
  ```python
  await check_budget(
      redis, SafeguardConfig.from_env(),
      user_id=job.user_id,
      tokens_to_reserve=estimate_tokens(full_prompt),
  )
  ```
  This supersedes the `estimated_input_tokens=0` placeholder we passed in Task 9.

- [ ] **Step 4: Commit**

---

## Task 18 — `.env.example` + README documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Append the safeguards block** to `.env.example` (see "Environment variables" section above).

- [ ] **Step 2: Add a README subsection** under the existing env-var docs titled "Safeguards (background jobs)". For each variable: name, purpose, default, acceptable values, and when to change it. British English, concise.

- [ ] **Step 3: Commit**

---

## Task 19 — Update `BACKGROUND-JOBS-DEBT.md` checklist

**Files:**
- Modify: `BACKGROUND-JOBS-DEBT.md`

- [ ] **Step 1: Check off every completed item**

  Walk the "Release-Checkliste" section. For each item now implemented, change `- [ ]` to `- [x]` and append the Task number in parentheses: `- [x] **C-001** — ... (Task 4 + 8)`.

- [ ] **Step 2: Add a "Pending" section** at the bottom listing M-001/M-002/M-003/M-004/M-005/L-001/L-002 with a note that they are intentionally deferred past this release.

- [ ] **Step 3: Commit**

  ```
  Check off completed items in BACKGROUND-JOBS-DEBT.md
  ```

---

## Task 20 — Full build + test sweep

- [ ] **Step 1: Backend syntax check for every modified file**

  ```bash
  uv run python -m py_compile \
    backend/main.py \
    backend/jobs/_submit.py \
    backend/jobs/_consumer.py \
    backend/jobs/_retry.py \
    backend/jobs/_models.py \
    backend/jobs/handlers/_memory_extraction.py \
    backend/jobs/handlers/_memory_consolidation.py \
    backend/jobs/handlers/_title_generation.py \
    backend/modules/chat/_orchestrator.py \
    backend/modules/llm/_adapters/_ollama_base.py \
    backend/modules/safeguards/_config.py \
    backend/modules/safeguards/_rate_limiter.py \
    backend/modules/safeguards/_queue_cap.py \
    backend/modules/safeguards/_budget.py \
    backend/modules/safeguards/_circuit_breaker.py \
    backend/modules/safeguards/__init__.py \
    backend/ws/router.py
  ```

- [ ] **Step 2: Full test run**

  ```bash
  uv run pytest -x -q
  ```

  Expected: all tests pass. If anything breaks in unrelated tests, fix the regression before moving on — do not proceed with known-red tests.

- [ ] **Step 3: Commit any final fixes**

- [ ] **Step 4: Merge to master** (per project convention — we are already on master).

---

## Self-review notes

- **Coverage vs `BACKGROUND-JOBS-DEBT.md`:** C-001 → T4+T8, C-002 → T10, C-003 → T11, C-004 → T12, H-001 → T13, H-002 → T14, H-003 → T15, H-004 → T16, H-005 → T12. SG-001 → T3, SG-002 → T5+T17, SG-003 → T2+T8, SG-004 → T11 (the per-user submit rate-limit inside `_process_extraction_keys`), SG-005 → T6. Medium/Low intentionally deferred.
- **Tooling assumptions:** `uv run pytest` is the project runner per `CLAUDE.md`. `redis-py` version was not checked — Task 3 explicitly tells the executor to verify before using `expire(..., nx=True)`.
- **Risks deferred on purpose:** M-001/M-003 (memory body & event-bus trim growth) are real, but not Ollama-cost issues; M-004 is replaced by SG-002; M-005 is mentioned opportunistically inside T10.
