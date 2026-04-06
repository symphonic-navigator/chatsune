# Backend Technical Debt

Generated: 2026-04-05. Covers all files under `backend/` and `shared/`.

---

## 1. Independently Fixable (no frontend changes needed)

---

### Critical / High Urgency

#### Low Effort

**[BD-001] Module boundary violation: `chat/_handlers.py` imports `PersonaRepository` directly**

- File: `backend/modules/chat/_handlers.py:11`
- Problem: `from backend.modules.persona._repository import PersonaRepository` is a hard CLAUDE.md violation. The `create_session` endpoint uses `PersonaRepository` directly to validate that a persona exists before creating a session.
- Why it matters: This is the first project convention explicitly listed as "STRICTLY ENFORCED" with a "FORBIDDEN" example. It creates a hidden coupling that will silently break if the persona module's internal structure changes.
- Fix: Add a `get_persona_for_session` or `find_persona_by_id` function to `backend/modules/persona/__init__.py` (it already has `get_persona`), then call that instead.

---

**[BD-002] Multiple critical topics missing from `_FANOUT` table -- events published but silently dropped**

- File: `backend/ws/event_bus.py:17-56`
- Problem: The following topics are published by handlers but are absent from `_FANOUT` and `_BROADCAST_ALL`, so `_fan_out()` logs a warning and does NOT deliver them to any WebSocket:
  - `Topics.CHAT_SESSION_PINNED_UPDATED` (published in `_handlers.py:194`)
  - `Topics.BOOKMARK_CREATED`, `Topics.BOOKMARK_UPDATED`, `Topics.BOOKMARK_DELETED` (published in bookmark handlers)
  - `Topics.CHAT_TOOL_CALL_STARTED`, `Topics.CHAT_TOOL_CALL_COMPLETED` (published in `_inference.py:175-193`)
  - `Topics.CHAT_WEB_SEARCH_CONTEXT` (published in `_inference.py:217`)
  - `Topics.SETTING_SYSTEM_PROMPT_UPDATED` (published in `settings/_handlers.py:52`)
  - `Topics.LLM_MODELS_FETCH_STARTED`, `Topics.LLM_MODELS_FETCH_COMPLETED` (published in `_metadata.py`)
- Why it matters: Real-time features silently fail. Pinning a session produces no UI update. Bookmark operations produce no UI update. Tool call progress indicators receive no data. These are confirmed delivery failures at runtime -- the warning log is the only indicator.
- Fix: Add each missing topic to `_FANOUT` with the appropriate `(roles, send_to_targets)` pair, or to `_BROADCAST_ALL` if applicable. All the bookmark/chat events should use `([], True)`.

---

**[BD-003] Refresh token `consume()` has a TOCTOU race condition**

- File: `backend/modules/user/_refresh.py:38-46`
- Problem: `consume()` does `GET` then a pipelined `DELETE`. Between the `GET` and `DELETE`, a second concurrent request with the same token can also read the token (it still exists), pass validation, and generate a new access token. This is a classic check-then-act race on a security token.
- Why it matters: Refresh token reuse is possible during race conditions -- two concurrent refresh calls with the same token can both succeed. This allows token theft exploitation without triggering the rotation guard.
- Fix: Replace the GET+pipeline approach with a Lua script or Redis `GETDEL` (available since Redis 6.2): `data = await redis.getdel(f"{_KEY_PREFIX}{token}")`. Then do the `SREM` afterwards (it's non-critical if it races).

---

**[BD-004] `_user_locks` dict grows forever -- memory leak per unique user**

- File: `backend/jobs/_lock.py:3-14`
- Problem: `_user_locks` is a plain dict that creates an `asyncio.Lock` for every user who ever triggers inference or a job. Locks are never removed. In a system with many users this will accumulate indefinitely.
- Why it matters: Low severity individually, but in a long-running process this is a guaranteed unbounded memory leak.
- Fix: Use a `WeakValueDictionary` (locks stay alive while held, collected when not in use), or implement an LRU cache with a bounded size and TTL-based eviction.

---

**[BD-005] `setup` endpoint has a TOCTOU race -- two master admins possible**

- File: `backend/modules/user/_handlers.py:99-101`
- Problem: The `setup` endpoint does `find_by_role("master_admin")` and then `repo.create(...)` as two separate operations. If two simultaneous setup requests arrive (e.g. from a misconfigured load balancer retry), both could pass the existence check before either insert completes.
- Why it matters: Results in two master_admin accounts, violating the uniqueness invariant the entire RBAC model relies on.
- Fix: Add a unique index on `role = "master_admin"` in `UserRepository.create_indexes()`, or use an upsert with a filter that prevents duplication.

---

**[BD-006] `OllamaCloudAdapter.stream_completion` has a 15-second timeout for the entire stream**

- File: `backend/modules/llm/_adapters/_ollama_cloud.py:22` (`_TIMEOUT = 15.0`)
- Problem: The `httpx.AsyncClient` is created with `timeout=_TIMEOUT` (15s). This is the connect + read timeout combined. A large model generating a long response will hit the read timeout mid-stream.
- Why it matters: All inference calls for non-trivial responses will time out with `ConnectError` or read timeout, producing a `provider_unavailable` error to the user.
- Fix: Split the timeout: use `httpx.Timeout(connect=15.0, read=None)` (unlimited read timeout) or a large read timeout like 300s.

---

#### Medium Effort

**[BD-007] `_run_inference` sends `ChatStreamStartedEvent` before acquiring the user lock**

- File: `backend/modules/chat/__init__.py:288-291`
- Problem: In the `LlmCredentialNotFoundError` catch block, `emit_fn` sends `ChatStreamStartedEvent` after `_runner.run()` has already been called. But `_runner.run()` itself also emits `ChatStreamStartedEvent` inside the lock. In the credential-not-found error path, two `chat.stream.started` events are emitted for the same error flow, confusing the frontend state machine.
- Fix: Have the runner propagate `LlmCredentialNotFoundError` before emitting the started event, or catch the error in `stream_fn` rather than in `_run_inference`.

---

**[BD-008] `delete_messages_after` uses timestamp comparison -- susceptible to same-millisecond collision**

- File: `backend/modules/chat/_repository.py:164-173`
- Problem: The method deletes messages where `created_at > target["created_at"]`. If two messages are saved within the same millisecond (MongoDB datetime resolution), the truncation logic in `handle_chat_edit` would leave stale messages.
- Fix: Add a monotonic sequence number to messages, or delete by `_id != target["_id"] AND session_id == session_id AND created_at >= target["created_at"]` to catch ties.

---

**[BD-009] `select_message_pairs` breaks at first pair that doesn't fit -- skips all older history**

- File: `backend/modules/chat/_context.py:56-60`
- Problem: The pair selection loop breaks on the *first* pair that exceeds the budget. A single large pair can cause the model to lose relevant older context that would otherwise fit.
- Fix: Use a greedy fit approach -- continue iterating even after a pair doesn't fit, rather than breaking. Or use a knapsack-style selection.

---

**[BD-010] `list_messages` has a hardcoded limit of 5000 -- unindexed for performance at scale**

- File: `backend/modules/chat/_repository.py:161-162`
- Problem: `list_messages` returns up to 5000 messages per session. Each call to `_run_inference` issues `list_messages` (for history), `list_messages` again in `save_fn` (for title generation check). For busy sessions, this is multiple large fetches per inference.
- Fix: Add a count-only method to `ChatRepository` (`count_messages(session_id)`), use it in `save_fn` for the title trigger check.

---

**[BD-011] `reorder_personas` issues N individual MongoDB updates -- no atomicity, no event published**

- File: `backend/modules/persona/_handlers.py:118-127`
- Problem: The reorder endpoint issues one `update_one` per persona in a Python loop. No transaction. If interrupted mid-loop, the order will be partially updated. No event is published for the reorder operation.
- Fix: Use `bulk_write` with multiple `UpdateOne` operations, optionally in a transaction. Add a `PERSONA_REORDERED` topic and publish the event.

---

**[BD-012] `reorder_bookmarks` has the same N-query and missing-event problems**

- File: `backend/modules/bookmark/_handlers.py:73-84` and `_repository.py:64-69`
- Problem: Identical issue to BD-011: N sequential `update_one` calls per bookmark, no atomicity, no WebSocket event published.
- Fix: Bulk write; publish a `BOOKMARK_REORDERED` event.

---

#### High Effort

**[BD-013] `get_model_context_window`, `get_model_supports_vision`, `get_model_supports_reasoning` each independently query the model cache**

- File: `backend/modules/llm/__init__.py:73-131`
- Problem: Each of these three functions calls `get_models(provider_id, redis, adapter)` independently. `_run_inference` calls all three in sequence. Each call creates a new adapter instance and does a Redis `GET`. On cache miss, it triggers three separate `fetch_models()` calls.
- Fix: Create a single `get_model_metadata(provider_id, model_slug) -> ModelMetaDto | None` function that fetches the model list once. Call it once in `_run_inference` and derive all three properties.

---

### Medium Urgency

#### Low Effort

**[BD-014] `list_users` returns unsorted results -- pagination is not stable**

- File: `backend/modules/user/_repository.py:58-62`
- Problem: `list_users` does `find().skip(skip).limit(limit)` with no sort. MongoDB does not guarantee document order without an explicit sort.
- Fix: Add `.sort("created_at", 1)` to the cursor.

---

**[BD-015] `login` checks inactive status after verifying the password**

- File: `backend/modules/user/_handlers.py:158-161`
- Problem: The login handler first verifies the password (expensive bcrypt comparison), then checks `is_active`. Wastes bcrypt cycles on known-invalid logins.
- Fix: Swap the order: check `is_active` before `verify_password`.

---

**[BD-016] `_TIMEOUT = 15.0` in websearch adapter is a flat timeout**

- File: `backend/modules/websearch/_adapters/_ollama_cloud.py:7`
- Problem: Same class of issue as BD-006. The websearch adapter uses a flat timeout.
- Fix: Use `httpx.Timeout(connect=10.0, read=30.0)`.

---

**[BD-017] `_background_tasks` module-level set in `ws/router.py` is never cleaned up on shutdown**

- File: `backend/ws/router.py:15`
- Problem: `_background_tasks` is a module-level `set[asyncio.Task]`. On application shutdown, any in-flight tasks are not explicitly cancelled or awaited. In-flight inference during shutdown will produce partial writes to MongoDB.
- Fix: In `lifespan`, before `disconnect_db()`, cancel all tasks in `_background_tasks` and await them with `asyncio.gather(*_background_tasks, return_exceptions=True)`.

---

**[BD-018] `get_current_user` uses a bare `except Exception` -- swallows all JWT errors identically**

- File: `backend/dependencies.py:16-18`
- Problem: Any exception from `decode_access_token` returns the same 401. Obscures important errors like `jwt.exceptions.InvalidAlgorithmError` that might indicate misconfiguration.
- Fix: Catch `jwt.ExpiredSignatureError` and `jwt.InvalidTokenError` specifically, and log unexpected exception types before returning 401.

---

**[BD-019] `tool_success` heuristic in `_inference.py` is unreliable**

- File: `backend/modules/chat/_inference.py:191`
- Problem: `success="error" not in result_str[:50].lower()` -- determines tool call success by checking if the first 50 characters contain the word "error". A web search result whose URL or title contains "error" would be incorrectly flagged as failed.
- Fix: Use `json.loads(result_str)` and check for the presence of an `"error"` key at the top level instead.

---

**[BD-020] `_user_role` index in `ConnectionManager` does not handle role changes for connected users**

- File: `backend/ws/manager.py:16`
- Problem: `_user_roles[user_id] = role` uses last-write-wins. If a user has their role changed by an admin, the stale role remains in `_user_roles` until they reconnect. `broadcast_to_roles` and `user_ids_by_role` will use the stale role.
- Fix: On `USER_UPDATED` event, refresh the user's role in `_user_roles` if the user is currently connected.

---

#### Medium Effort

**[BD-021] `delete_stale_empty_sessions` does not cascade delete bookmarks**

- File: `backend/modules/chat/_repository.py:101-121`
- Problem: The stale session cleanup deletes sessions directly from MongoDB using `delete_many`. Unlike `delete_session` (which calls `delete_bookmarks_for_session`), the cleanup path does NOT cascade to bookmarks.
- Fix: Fetch stale session IDs, use a bulk delete on bookmarks with `session_id: {"$in": stale_ids}`, then delete the sessions.

---

**[BD-022] `OllamaCloudAdapter.stream_completion` creates a new `httpx.AsyncClient` for each call**

- File: `backend/modules/llm/_adapters/_ollama_cloud.py:128-161`
- Problem: Every streaming inference call creates and destroys an httpx client, bypassing connection pooling. TCP connection establishment overhead per inference call.
- Fix: Create a module-level or class-level `httpx.AsyncClient` with connection pooling, or use a dependency-injected client.

---

**[BD-023] `delete_messages_after` + `update_message_content` in `handle_chat_edit` are not atomic**

- File: `backend/modules/chat/__init__.py:429-446`
- Problem: The edit handler does two separate MongoDB operations with no transaction. If the process crashes between them, the session is left with messages deleted but the target message not yet updated.
- Fix: Wrap both operations in a `async with await client.start_session() as session: async with session.start_transaction()` block.

---

### Low Urgency

#### Low Effort

**[BD-024] `_TWENTY_FOUR_HOURS_MS` trim in `event_bus.py` only triggers on publish**

- File: `backend/ws/event_bus.py:103-108`
- Problem: `xtrim` with `minid` is only applied *after* each publish, not proactively. High-traffic streams will accumulate entries between trims.
- Fix: Add a periodic `xtrim` background task, or switch to `MAXLEN ~` in addition to the `MINID` trim.

---

**[BD-025] `validate_key` in `OllamaCloudAdapter` can return `None` implicitly on non-200/401/403 status**

- File: `backend/modules/llm/_adapters/_ollama_cloud.py:115-127`
- Problem: The method calls `resp.raise_for_status()` on unexpected status codes. Python's type checker will flag the implicit `None` return path.
- Fix: Add an explicit `return False` after `raise_for_status()` (unreachable but makes intent clear to type checkers).

---

**[BD-026] `CreateUserRequestDto.display_name` lacks validation but `UpdateDisplayNameDto` has it**

- File: `shared/dtos/auth.py:31-34` vs `shared/dtos/auth.py:86-94`
- Problem: `UpdateDisplayNameDto` has `max_length=64` and a non-blank validator. `CreateUserRequestDto.display_name` has no such constraints.
- Fix: Apply the same `max_length=64` and non-blank validator to `CreateUserRequestDto.display_name`.

---

**[BD-027] `about_me` field has no length limit**

- File: `shared/dtos/auth.py:82-83`
- Problem: `UpdateAboutMeDto.about_me` is typed as `str | None` with no length constraint. A user could submit an arbitrarily large string that is assembled into the system prompt on every inference call.
- Fix: Add `Field(max_length=4000)` or similar to `UpdateAboutMeDto.about_me`.

---

**[BD-028] No rate limiting or brute-force protection on `/api/auth/login`**

- File: `backend/modules/user/_handlers.py:153-180`
- Problem: The login endpoint has no rate limiting. A single IP can attempt unlimited password guesses.
- Fix: Implement per-IP rate limiting via Redis (`INCR + EXPIRE`), or use a FastAPI middleware like `slowapi`.

---

**[BD-029] `get_avatar` endpoint accepts a `token` query parameter -- token in URL is logged by every proxy/CDN**

- File: `backend/modules/persona/_handlers.py:339-374`
- Problem: The avatar endpoint accepts JWT via `?token=...` query parameter to support `<img src>` tags. JWT tokens in URLs appear in server logs, CDN access logs, browser history, and `Referer` headers.
- Fix: Consider serving avatar images via a short-lived signed URL or a separate cookie-authenticated endpoint.

---

**[BD-030] `system_prompt` (persona + admin + model instructions + about_me) has no combined length cap**

- File: `backend/modules/chat/_prompt_assembler.py:38-79`
- Problem: The assembler concatenates all four layers without checking the combined length against the context window. If it exceeds `max_context_tokens`, `calculate_budget` returns `available_for_chat = 0`.
- Fix: After `assemble()`, check `system_prompt_tokens > max_context * 0.5` and emit a warning or truncate.

---

#### Medium Effort

**[BD-031] `_FANOUT` admin events broadcast to ALL admins, no resource-level scoping**

- File: `backend/ws/event_bus.py:17-22`
- Problem: `Topics.USER_CREATED` broadcasts to all `"admin"` and `"master_admin"` connected users. `USER_UPDATED` and `USER_DEACTIVATED` send changed fields to all admins, which may include sensitive fields.
- Fix: Document this as a known scope limitation. Add a comment noting that admin fan-out is flat and must be revisited if per-admin scoping is added.

---

**[BD-032] `persona/_handlers.py` imports `decode_access_token` directly from `_auth` module**

- File: `backend/modules/persona/_handlers.py:30` and `:347`
- Problem: `from backend.modules.user._auth import decode_access_token` -- cross-module internal import (forbidden per CLAUDE.md). `decode_access_token` is already exported via `backend.modules.user.__init__`.
- Fix: Use `from backend.modules.user import decode_access_token`.

---

**[BD-033] `UserModelConfigRepository.upsert` has a find-then-insert race condition**

- File: `backend/modules/llm/_user_config.py:37-62`
- Problem: `upsert` calls `find()` then either `update_one` or `insert_one`. Two concurrent upsert calls can both find no existing document and both try to insert, raising an unhandled `DuplicateKeyError`. Same pattern in `CredentialRepository.upsert` and `CurationRepository.upsert`.
- Fix: Use MongoDB's `update_one` with `upsert=True` and `$setOnInsert` for the immutable fields.

---

## 2. Requires Frontend Coordination

---

### Critical / High Urgency

#### Low Effort

**[BD-034] Ephemeral tool/search events should be in `_SKIP_PERSISTENCE` once added to `_FANOUT`**

- File: `backend/ws/event_bus.py:65-68`
- Problem: `CHAT_TOOL_CALL_STARTED`, `CHAT_TOOL_CALL_COMPLETED`, and `CHAT_WEB_SEARCH_CONTEXT` are not in `_SKIP_PERSISTENCE`. Once added to `_FANOUT` (see BD-002), they would be persisted to Redis Streams. These are ephemeral in-flight events meaningless on reconnect.
- Fix: Once BD-002 is resolved, add these topics to `_SKIP_PERSISTENCE`.

---

**[BD-035] Session `state` is not reset to `"idle"` when WebSocket client disconnects during streaming**

- File: `backend/ws/router.py:99-106` and `backend/modules/chat/__init__.py:204-205`
- Problem: When a user disconnects, any in-flight inference task continues running. If the task errors out in a way that skips `save_fn`, the session is permanently stuck as `"streaming"`.
- Why it matters: On reconnect, the user can never send a new message to a stuck-streaming session.
- Fix: In `save_fn` and the error handlers, always call `repo.update_session_state(session_id, "idle")`. Review the `finally` block to ensure state reset is unconditional.

---

### Medium Urgency

#### Low Effort

**[BD-036] `ChatSessionPinnedUpdatedEvent` is published but never delivered (duplicate of BD-002)**

- The frontend relies on this event to update the pinned state in the session list without refetching. Its absence means pinning/unpinning appears to fail from the user's perspective.

---

#### Medium Effort

**[BD-037] `chat.session.created` event carries ISO string dates rather than datetime objects**

- File: `shared/events/chat.py:81-91`
- Problem: `ChatSessionCreatedEvent.created_at` and `updated_at` are typed as `str` and set using `.isoformat()`. Every other event uses `datetime` fields. The frontend must parse these fields differently.
- Fix: Change to `created_at: datetime` and `updated_at: datetime`. This requires the frontend to handle the changed wire format.

---

**[BD-038] `handle_incognito_send` always enables all tool groups -- no session-level toggle respected**

- File: `backend/modules/chat/__init__.py:587`
- Problem: `active_tools = get_active_definitions([]) or None` -- incognito send always passes an empty `disabled_groups` list, enabling all tools regardless of what the client passed.
- Fix: Accept `disabled_tool_groups` in the `chat.incognito.send` WebSocket message payload and pass it through, or document that incognito mode always enables all tools.
