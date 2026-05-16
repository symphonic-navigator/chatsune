# PRE-BRANCHING — Hardening Audit before v0.2.0

**Date:** 2026-05-16
**Audience:** Chris + Claude Code
**Scope:** Pre-work before implementing **branching** as flagship feature for v0.2.0.

Branching forks a conversation from any message into a tree of variations. It
multiplies every existing context-handling bug across each fork and exposes
schema assumptions that are currently linear-only. Before we add forks, we
need to harden the foundation: context handling, reasoning/tool re-injection,
compact-and-continue, and frontend event handling.

Four parallel investigation agents produced the findings below. Severity is
the agent's own judgement; "branching impact" describes how the issue
deteriorates once forks exist.

---

## TL;DR — Executive Summary

**Three findings would block branching outright** and must be addressed
before any branching code lands:

1. `edit_message_atomic` is destructive: it hard-deletes everything after the
   target message. Branching by definition needs forks, not truncation.
   (a-9, `backend/modules/chat/_repository.py:987-1017`)
2. **Reasoning content and tool calls are never re-injected across turns.**
   The history loop reads only `doc["content"]`; `doc["thinking"]` and
   `doc["events"]` are silently dropped. A branch that includes a
   reasoning- or tool-using turn becomes a strictly weaker conversation than
   the original. (b-1, b-3, `backend/modules/chat/_orchestrator.py:852-871`)
3. **The compaction checkpoint array lives on `ChatSessionDocument`.** If
   branches share a session document, a re-compaction on branch A
   contaminates branch B. Either branches must be separate documents or each
   branch must own its own checkpoint chain. (c-10, design question.)

**Several findings are independently shippable hardening wins** regardless
of branching — see [Low-Hanging Fruits](#low-hanging-fruits) at the bottom.

**Several findings are upstream-correctness bugs** that the team should
fix before branching even if they don't strictly block it: silent history
truncation at 5000 messages, two-tab race poisoning history, mid-stream
crash losing the entire reply, compaction lock not honoured by the chat-send
handler, generic `Topics.ERROR` events dropped on the floor.

---

## (a) Context handling

### Pattern as built today

A chat session is a linear, append-only sequence of message documents in the
`chat_messages` collection, ordered by `created_at`. The writer is
`ChatRepository.save_message` (`backend/modules/chat/_repository.py:794`). The
user message is persisted before inference starts; the assistant message is
persisted exactly once at end-of-stream, after the runner has accumulated
the full `content` + `thinking` + tool-call timeline in memory. Streaming
deltas (`CHAT_CONTENT_DELTA`, `CHAT_THINKING_DELTA`,
`CHAT_TOOL_CALL_DELTA`) are explicitly excluded from Redis-stream
persistence (`backend/ws/event_bus.py:227`), so in-flight content exists
only in the runner's process memory until the single save-fn call. Inference
reads history via `repo.list_messages(session_id)`
(`backend/modules/chat/_orchestrator.py:764`), filters aborted/refused docs
(`_filter_usable_history`, line 71), then pair-selects backwards into the
available token budget (`select_message_pairs`,
`backend/modules/chat/_context.py:42`). Mutators are limited to
`edit_message_atomic` (destructive truncation),
`delete_message` (regenerate), and the compaction job's append-only
checkpoint write.

### Findings

**a-1. Mid-stream assistant content lost on process crash or `save_fn` exception.**
*Severity: High. Confidence: High.*
`backend/modules/chat/_inference.py:235-826` accumulates `full_content`
purely in memory; persistence happens exactly once at end-of-stream
(`backend/modules/chat/_orchestrator.py:1038-1082`). If FastAPI is killed,
Mongo blips on insert, or `save_fn` itself raises, the assistant reply is
not persisted and no `ChatStreamEndedEvent` fires — the frontend "thinking"
indicator stays stuck. *Branching impact:* every long fork becomes its own
single point of failure.

**a-2. `select_message_pairs` silently drops history that is not strict user/assistant alternation.**
*Severity: High. Confidence: High.*
`backend/modules/chat/_context.py:42-80`. After `_filter_usable_history`
drops an aborted assistant, the sibling user message remains; the pair
builder advances `i += 1` (line 59) on non-matching alternation and never
includes the user message in the LLM context. The model has no idea the
user said anything on that turn. Two-tab races (a-3) make this fire more
often. *Branching impact:* branches frequently inherit aborted-mid-tail
histories — pair-matching drops them inconsistently across siblings,
"regenerate from this point" becomes non-deterministic.

**a-3. Two-tab race produces interleaved writes with no ordering guarantee.**
*Severity: High. Confidence: High.*
`backend/modules/chat/_handlers_ws.py:185-366`,
`backend/modules/chat/_orchestrator.py:231-247`.
`cancel_inflight_for_session` only signals; it does not await the cancelled
inference's `save_fn`. Sequence: user types A in tab 1; user types B in tab
2 at T2; cancelled inference for A finishes its final flush and inserts at
T3 > T2. History reads as `user A → user B → assistant-for-A`; pair-matching
then pairs `user B` with `assistant-for-A`. *Branching impact:* branches
multiply the race windows.

**a-4. `created_at` is microsecond-resolution timestamp ordering; `delete_messages_after` uses `$gte` not `$gt`.**
*Severity: Medium. Confidence: Medium.*
`backend/modules/chat/_repository.py:950-960`, `:1000-1006`. Two messages
inserted within the same Python tick share `created_at`; the truncation
query then deletes the wrong neighbour. Reload sort is `_id`-tiebroken =
UUIDv4 = random. *Branching impact:* branching needs "messages 0..N in this
branch share with parent" — that cannot be expressed with timestamps as
both clock and lineage. **Schema change with a migration** —
recommendation: add monotonic `session_seq: int`.

**a-5. `list_messages` silently truncates at 5000 — and returns the *oldest* 5000.**
*Severity: Medium. Confidence: High.*
`backend/modules/chat/_repository.py:918-920`. `to_list(length=5000)` with
`sort created_at: 1` keeps the oldest, drops the newest. A session at 5001
messages loses its most recent turns, the model is confused, the user is
confused, no warning emitted. Easy fix: tail-load variant + warning.

**a-6. Token counting drift: thinking, attachments, and provider tool-schema overhead all uncounted.**
*Severity: Medium. Confidence: High.*
`backend/token_counter.py` uses `cl100k_base` for everything;
`backend/modules/chat/_orchestrator.py:1046` counts only `content` on save;
`backend/modules/chat/_orchestrator.py:985-989` ignores provider wrapping
on tool definitions. The ampel pill says 40% full while Anthropic returns
`input_tokens` of 70% full. The 0.80 hard-stop fires inconsistently across
adapters. *Branching impact:* branching off a session that's already over
the real limit produces immediate `context_window_full` errors on the very
first turn.

**a-7. `context_window_full` hard-stop fires *after* the user message was persisted.**
*Severity: Medium. Confidence: High.*
`backend/modules/chat/_handlers_ws.py:275` inserts the user message; then
`backend/modules/chat/_orchestrator.py:825` computes fill-ratio and returns
without inference if ≥ 0.80. Result: user message in history with no
assistant reply — dangling odd-numbered tail — pair-matching then breaks
for every subsequent attempt. The error event also uses a freshly-generated
correlation_id (line 826), severing it from the original send.
*Branching impact:* orphan user messages fan out per branch.

**a-8. Reconnect mid-stream replays no deltas — user sees a frozen partial message.**
*Severity: Medium. Confidence: High.*
`backend/ws/event_bus.py:227-240` skips delta persistence (correct — keeps
Redis small); `backend/ws/router.py:198-272` replays only persistent
events. WS reconnect inside the grace window sees `chat.stream.started`
again but no content until the run finishes. With branching, longer
streams = more reconnects = more "looks frozen" complaints.

**a-9. `edit_message_atomic` is hard-delete — branching needs forks, not truncation.**
*Severity: High. Confidence: High (for branching).*
`backend/modules/chat/_repository.py:987-1017`. **This is the schema
blocker.** The current model treats history as a single linear tape;
branching by definition keeps the original tail alive. Needs
`parent_message_id` + `branch_id` (or per-branch session documents).
Compaction checkpoints become per-branch.

**a-10. Aborted user message remains pollution after compaction.**
*Severity: Low. Confidence: Medium.*
`backend/modules/chat/_orchestrator.py:71-80`, `:780-784`. Filter drops the
aborted assistant but leaves the user message. Compaction `tail_start` may
point at the orphan; if that user message is later edited or deleted,
`compaction.checkpoint.dangling` errors out the next inference.

**a-11. Token "used" displayed to user is whole history; provider sees only selected pairs.**
*Severity: Low. Confidence: High.*
`backend/modules/chat/_orchestrator.py:821, 999`. UI ampel reflects "what
fits in this session", which differs from "what was actually sent". User
sees 70% full and starts a new session prematurely. Additive DTO fix.

---

## (b) Reasoning + tool-result re-injection

### Pattern as built today

**Within a turn,** the inference loop accumulates `iter_content`,
`iter_thinking`, `iter_tool_calls` plus per-iteration usage
(`backend/modules/chat/_inference.py:278-284`). When tools fire, the loop
pushes one `CompletionMessage(role="assistant", content=[text],
tool_calls=[…])` plus one `role="tool"` message per call into
`extra_messages` (`_inference.py:529-542`, `:783-787`) and re-sends them on
the next iteration of the same turn. Commit `ad38b914` ensures
`iter_content` is **not** reset between iterations — `full_content` folds
cumulatively across all iterations.

**Across turns,** the picture is much thinner. The repository stores
`content`, `thinking`, and a chronological `events` timeline
(`backend/modules/chat/_repository.py:825-871`). On the next user turn,
the orchestrator's history loop
(`backend/modules/chat/_orchestrator.py:852-871`) reads only
`doc["content"]` + attachments + vision snapshots. **`doc["thinking"]`,
`doc["events"]`, and the legacy `doc["tool_calls"]` are silently dropped
before the prompt is built.** The `CompletionMessage` DTO itself has no
thinking/signature/reasoning_content field
(`shared/dtos/inference.py:21-25`).

### Per-adapter matrix

| Adapter | Reads reasoning | Pushes reasoning back | tool_call_id round-trip | Signature handling |
|---|---|---|---|---|
| `_openrouter_http.py:248-258, 305-346` | `reasoning_content` + `reasoning` | **No** | Yes | **No** — `reasoning_details` ignored |
| `_xai_http.py:178-180, 237-272` | `reasoning_content` | **No** | Yes | Hard-CoT chain not preserved |
| `_ollama_http.py:135-149, 554-556` | `message.thinking` | **No** | **No** (`tool_call_id` ignored) | n/a |
| `_mistral_http.py:160-197, 303-338` | typed-array `thinking` + `reasoning_content` | **No** | Yes | Mistral typed-thinking ack ignored |
| `_chutes_http.py:337-341, 162-192` | `reasoning_content` | **No** | Yes | n/a |
| `_tensorix_http.py:252-276, 310-…` | `reasoning_content` | **No** | Yes | n/a |
| `_novita_http.py:136-138, 271-…` | `reasoning_content` | **No** | Yes | n/a |
| `_nano_gpt_http.py:185-189, 258-…` | `reasoning` + `reasoning_content` | **No** | Yes | n/a |
| Drivers (`deepseek_v4`, `kimi_k2`, `mimo_v25`) | yes, soft-CoT-parsed | **No** | depends on host adapter | `reasoning_details` discarded |

There is no native Anthropic adapter — Claude is reached via OpenRouter or
nano-gpt in OpenAI-compat shape.

### Findings

**b-1. Thinking content never re-injected across turns.**
*Severity: High. Confidence: High.*
`backend/modules/chat/_orchestrator.py:852-871` reads `doc["content"]`
only. Anthropic, xAI hard-CoT, and Mistral hard-CoT all lose their
reasoning trace on every subsequent turn. Anthropic docs are categorical:
extended-thinking blocks must be sent back during a tool-use conversation
with their signature exactly as received. We do neither.

**b-2. Anthropic `signature` not captured, full stop.**
*Severity: Critical for Claude reasoning + tools. Confidence: High.*
`backend/modules/llm/_adapters/_openrouter_http.py:248-258` and
`backend/modules/llm/_adapters/_nano_gpt_http.py:185-189`. Both parsers
read `delta.reasoning` (string) and ignore `delta.reasoning_details[*]`,
where OpenRouter forwards Anthropic-native `{"type":"thinking", "thinking":
"...", "signature": "<opaque>"}` blocks. No persistence path captures
signatures. A branch of a Claude reasoning+tools conversation will be
rejected or silently degraded by the provider.

**b-3. Tool calls and tool results never re-injected across turns.**
*Severity: High. Confidence: High.*
Same location as b-1. A turn that called `web_search` is presented to the
next turn as plain assistant text. The model has no record it ever issued
the search, what arguments it used, or what came back. Multi-turn
tool-augmented sessions today are technically degraded; for branching they
are unworkable. The data is already on each timeline entry
(`result_content` — `backend/modules/chat/_inference.py:114, 763, 778`);
the expansion logic to re-emit `assistant(tool_calls) + tool(tool_call_id,
result)` triplets is new but localised to the orchestrator.

**b-4. Ollama tool messages drop `tool_call_id`.**
*Severity: Medium. Confidence: High.*
`backend/modules/llm/_adapters/_ollama_http.py:135-149`. `_translate_message`
ignores `msg.tool_call_id` entirely. Native Ollama tool protocol does not
require id correlation, but Ollama-Cloud-hosted models that follow OpenAI
shape (e.g. GLM-5) do. Three-line fix.

**b-5. Soft-CoT thinking is correctly stripped — but for the wrong reason.**
*Severity: Low. Confidence: Medium.*
`backend/modules/chat/_soft_cot_parser.py:152-170`,
`backend/modules/chat/_orchestrator.py:1033`. DeepSeek-R1 / Kimi / MiMo /
GLM-5 must not see their previous turn's `<think>` block. Today we don't
replay any thinking at all, so this works by accident — the same accident
that breaks Anthropic. Once b-1 is fixed, the strip-vs-replay decision must
be capability-gated (proposal: `ReasoningCapability.replay_reasoning: bool`).

**b-6. Empty assistant from a refused turn poisons history if mis-saved.**
*Severity: Low. Confidence: Medium.*
`backend/modules/chat/_orchestrator.py:71-80`,
`backend/modules/chat/_inference.py:813-826`. A turn that used tools and
produced only partial assistant text before being cancelled gets
`status="aborted"` and is skipped — but the tool's side effects
(`write_journal_entry`, `generate_image`) already happened. Branching from
such a message is undefined; product call needed.

**b-7. xAI cache hint is sent but reasoning round-trip is missing.**
*Severity: Low. Confidence: High.*
`backend/modules/llm/_adapters/_xai_http.py:178-180`. grok hard-CoT cache
benefit is partially wasted; the reasoning trace is dropped between turns.
Same root cause as b-1.

**b-8. Cumulative preamble fix is only correct because nothing replays.**
*Severity: Low. Confidence: High.*
`backend/modules/chat/_inference.py:544-551` (commit `ad38b914`). When b-3
ships, the assistant doc will contain cumulative narration **plus** the
expanded `tool_calls`/`tool_results` triplets — narration AND structured
calls. Tolerated by models in practice but adds redundancy. Decide whether
to split the narration at timeline entry boundaries when expanding.

### Configurability proposal

Two capability-driven knobs, both with sensible defaults:

1. **`ReasoningCapability.replay_reasoning: bool`** in
   `shared/dtos/llm.py` and `backend/modules/llm/data/model_capabilities.yaml`.
   `True` for hard-CoT families (Anthropic, xAI reasoning, OpenAI o-series,
   Mistral hard-CoT); `False` for soft-CoT families (DeepSeek-R1, Kimi,
   MiMo, GLM-5). The orchestrator consults this when expanding history.
2. **`ChatSessionExtras.replay_tool_history: bool`** (default `True`),
   user-tunable. When `False`, the orchestrator collapses past tool-call
   narration into the assistant's text only — useful for branching off old
   conversations where the tool results are stale (e.g. last week's web
   search).

---

## (c) Compact-and-continue

### How it works today

1. **Trigger** — user clicks the sparkly button
   (`frontend/src/features/chat/compaction/SparkleCompactButton.tsx`);
   confirm card; WS `chat.compaction.request`; routes to
   `handle_chat_compaction_request`
   (`backend/modules/chat/_handlers_ws.py:877`).
2. **Pre-flight** — ownership + minimum-size + 30% floor; acquire Redis
   lock `compaction:lock:{session_id}` with `nx=True, ex=600`; compute
   tail via `determine_tail_start_index`
   (`backend/modules/chat/_compaction.py:18-54`); sanitise source; reject
   "nothing new" / "source too large"; submit `JobType.CHAT_COMPACTION`
   job; emit `ChatCompactionStartedEvent`.
3. **Job handler** (`backend/jobs/handlers/_chat_compaction.py`) — re-runs
   tail helpers; truncates source from front until ≤ 70% of model context;
   builds system prompt (`_compaction.py:169-203`) and transcript
   (`_compaction.py:206-248`, prepending the previous checkpoint's
   `summary_markdown` on re-compact); calls `stream_completion`
   (temperature 0.3, no tools, no reasoning); validates six required
   sections; retries once with reminder appendix; `$push`-es the
   `CompactionCheckpoint` to the session document; updates
   `context_used_tokens` and `context_fill_percentage`; emits
   `ChatCompactionCompletedEvent`; releases the Redis lock in `finally`.
4. **Frontend** (`frontend/src/features/chat/useChatStream.ts:586-658`) —
   `STARTED` sets `compactionLoading`; `COMPLETED` appends checkpoint and
   updates metrics; `FAILED` shows retry toast; 90 s soft-timeout
   (`frontend/src/features/chat/ChatView.tsx:757-771`) drops the loading
   flag with a "running long" notification.
5. **Next-turn assembly** — `backend/modules/chat/_orchestrator.py:760-1018`
   slices `history_docs` to messages with `created_at >= tail_start_msg.created_at`
   and passes the latest `summary_markdown` to `_prompt_assembler.assemble()`
   which injects a `<conversation_compact>` XML block
   (`backend/modules/chat/_prompt_assembler.py:170-179`); the compact
   anchor index feeds the Anthropic cache-marker strategy
   (`backend/modules/llm/_adapters/_anthropic_cache.py:74-93`).

### Findings

**c-1. Backend `handle_chat_send` does not honour the compaction lock.**
*Severity: High. Confidence: High.*
`backend/modules/chat/_handlers_ws.py:185-368`. The Redis lock is only
checked in the compaction trigger; the chat-send path has no awareness of
it. A user message arriving between job-submit and job-completion (second
tab, scripted client, WS catch-up replay) fires inference against the full
history with no checkpoint visible yet. Two concurrent writers to
`update_session_context_metrics` produce inconsistent metrics. *Branching
impact:* a branch-with-immediate-send while compaction is in flight on the
parent streams against pre-compact state.

**c-2. Compaction job catches all exceptions before consumer sees them — no real retries.**
*Severity: Medium. Confidence: High.*
`backend/jobs/handlers/_chat_compaction.py:64-237`. Outermost `try`
swallows `Exception`, emits `CHAT_COMPACTION_FAILED`, returns normally.
Consumer treats that as success, the configured `max_retries=1` and
`notify_error=True` (`backend/jobs/_registry.py:79-88`) are dead.
Transient LLM failures never auto-recover.

**c-3. No daily-token-budget reservation in the compaction handler.**
*Severity: Medium. Confidence: High.*
`backend/jobs/handlers/_chat_compaction.py` vs the budget pattern in
`backend/jobs/handlers/_memory_consolidation.py:176, 208`. SG-002 daily
limit can be exceeded by repeated compactions. A retry-loop under failure
blows through the cap silently. *Branching impact:* branch-spawn-and-compact
patterns multiply the spend; potential cost-exfiltration vector.

**c-4. Lock leak on trigger-handler exceptions between acquire and submit.**
*Severity: Medium. Confidence: High.*
`backend/modules/chat/_handlers_ws.py:931-1093`. If anything between the
`redis.set(nx=True, ex=600)` and `submit_job` raises, control reaches the
outer `except Exception` at line 1088 and the lock is held for the full
600 s TTL. User clicking Retry within 10 min gets "already_running".

**c-5. Post-compaction context metrics undercount system-prompt overhead.**
*Severity: Low. Confidence: High.*
`backend/jobs/handlers/_chat_compaction.py:176-186`. `new_used =
tokens_after + tail_token_count` excludes admin prompt, persona, memory,
integration extensions, the `<conversation_compact>` envelope, and tool
definitions. The pill is 2-5k tokens too rosy until the next inference
corrects it. Fix: invoke `assemble()` after persisting and add that count.

**c-6. Transcript drops attachment/image/artefact metadata.**
*Severity: Medium. Confidence: Medium.*
`backend/modules/chat/_compaction.py:206-235` renders only `content`.
Attachments (`attachment_refs`), generated images (`image_refs`), artefacts
(`artefact_refs`), and prior vision descriptions never reach the
summariser, so the "Pending References" section of the briefing is
incomplete. *Branching impact:* branches frequently diverge over an
attachment — losing those refs collapses branches into indistinguishable
summaries.

**c-7. `regenerate` and `edit` paths can run during compaction.**
*Severity: Medium. Confidence: High.*
`backend/modules/chat/_handlers_ws.py:371` (`handle_chat_edit`),
`:536` (`handle_chat_regenerate`). Same problem as c-1, plus a race where
the source range references a message that gets deleted/edited before
job persistence.

**c-8. Frontend 90 s soft-timeout silently abandons UI lock; backend job may still complete.**
*Severity: Low. Confidence: High.*
`frontend/src/features/chat/ChatView.tsx:752-771`. After 90 s the overlay
disappears, user is free to send messages, then the real
`CHAT_COMPACTION_COMPLETED` arrives 30 s later → race with the user's
in-flight chat-send. Simplest fix: raise the soft-timeout to the job's
`execution_timeout_seconds=120` plus a small buffer (~150 s).

**c-9. Branching composition: no design for "branch from a compacted-out message".**
*Severity: High. Confidence: High.*
Conceptual — no branching code exists yet. Natural UX is "right-click a
message → branch from here". If the target message is older than the
latest checkpoint's `tail_start_message_id`, the prefix cannot be
reconstructed verbatim because source messages may have been pruned
(`backend/jobs/handlers/_chat_compaction.py:121-128` truncates the
oldest). Recommendation: mirror the existing `edit_before_compact` guard
for `branch_from`.

**c-10. Branching composition: independent re-compaction across branches.**
*Severity: Medium. Confidence: Medium.*
`compaction_checkpoints` lives on `ChatSessionDocument`. If branches share
a session document, a re-compaction on branch A contaminates branch B.
Either: separate session documents per branch (clone-on-branch), or each
branch carries its own checkpoint array. **Decide before branching ships.**

**c-11. Stale `prev_checkpoint_id` payload — race between trigger snapshot and job execution.**
*Severity: Low. Confidence: Medium.*
`backend/modules/chat/_handlers_ws.py:979-980` vs
`backend/jobs/handlers/_chat_compaction.py:78-84`. If c-4 fires and the
lock leaks, the second job could see a stale id. Defensive fix: job
handler always uses `checkpoints[-1]` and treats the payload as a sanity
check.

**c-12. Frontend `compactionLoading` is a single global flag.**
*Severity: Low. Confidence: Medium.*
`frontend/src/core/store/chatStore.ts:529-533`,
`frontend/src/features/chat/useChatStream.ts:589-606`. Cross-session UX
not deliberately designed. Recommendation: scope per-session, or enforce
"one compaction per user at a time" backend-side.

**c-13. Validation retry uses same temperature and same correlation id.**
*Severity: Low. Confidence: High.*
`backend/jobs/handlers/_chat_compaction.py:305-358`. Small Ollama models
that don't follow instructions twice will fail again on the user-triggered
retry. Cosmetic improvement.

**c-14. No reversibility / undo path.**
*Severity: Low. Confidence: High.* Spec §10 explicitly excludes
"compact-stack". If a summary is poor, the user's only recovery is to
start a new session or wait for the next compaction to fold it in.

**c-15. Token-count accuracy not bounded.**
*Severity: Medium. Confidence: Medium.*
`backend/jobs/handlers/_chat_compaction.py:158` uses `cl100k_base`.
Anthropic/xAI/Mistral tokenisers differ — actual provider cost can be 10-30%
higher. Same root cause as a-6.

### Prime-time readiness checklist

- [ ] Block `chat.send` / `chat.edit` / `chat.regenerate` while compaction
      lock is held (c-1, c-7). Backend-enforced.
- [ ] Wire SG-002 budget into the compaction handler (c-3).
- [ ] Fix lock leak on trigger-handler exception path (c-4).
- [ ] Decide compaction handler error semantics (c-2) — retry or remove dead config.
- [ ] Surface attachment / image / artefact metadata in the briefing transcript (c-6).
- [ ] Recompute post-compact metrics from the real assembled system prompt (c-5).
- [ ] Match the UI soft-timeout to the job execution timeout (c-8).
- [ ] Verify upgrade path on a session with old documents (CLAUDE.md hard rule).
- [ ] **Design how branching composes with compaction before shipping
      branching** (c-9, c-10). Documented decision: can you branch from a
      source-range message; do branches share or clone checkpoint arrays.
- [ ] Verify Auto-Mode + discovery-dialog scope for v0.2.0 — spec §6.0/§6.5
      describes them, no implementation found.
- [ ] Test WS disconnect mid-compaction — Redis Streams catch-up must deliver
      `STARTED`/`COMPLETED` in order.
- [ ] Confirm Anthropic cache-marker math across all four adapters; marker
      count limit is 4, must not collide with `cache_hint`.
- [ ] Test re-compact three consecutive times on one session — "Previous
      Story" block must not balloon.
- [ ] Test `compaction_source_too_large` rejection on small-context models.

---

## (d) Frontend conversation UX + event handling

### Event-handler coverage matrix

| Topic | Backend emits | Frontend handler | Notes |
|---|---|---|---|
| `chat.stream.started` | ✓ | `useChatStream.ts:60` | OK |
| `chat.content.delta` | ✓ | `useChatStream.ts:104` | gated by Group, not slot |
| `chat.thinking.delta` | ✓ | `useChatStream.ts:116` | gated by slot |
| `chat.stream.slow` | ✓ | `useChatStream.ts:122` | OK |
| `chat.stream.ended` | ✓ | `useChatStream.ts:254` | OK |
| `chat.stream.error` | ✓ | `useChatStream.ts:413` | not all subcodes specially handled |
| `chat.vision.description` | ✓ | `useChatStream.ts:128` | OK |
| `chat.tool_call.*` | ✓ | `useChatStream.ts:139-162` | OK |
| `chat.web_search.context` | ✓ | `useChatStream.ts:242` | OK |
| `chat.client_tool.dispatch` | ✓ | `clientToolHandler.ts:38` | **no timeout, no session/correlation gate** |
| `chat.message.created` | ✓ | `useChatStream.ts:519` | OK |
| `chat.messages.truncated` | ✓ | `useChatStream.ts:552` | OK |
| `chat.message.updated` | ✓ | `useChatStream.ts:557` | OK |
| `chat.message.deleted` | ✓ | `useChatStream.ts:562` | OK |
| `chat.session.title_updated` | ✓ | OK | |
| `chat.session.created` | ✓ | `useChatSessions.ts:29` | OK |
| `chat.session.deleted` | ✓ | `ChatView.tsx:627`, others | OK |
| **`chat.session.restored`** | ✓ | `useChatSessions.ts:82` only | **NOT handled in `ChatView`** |
| `chat.session.toggles_updated` | ✓ legacy | `useChatStream.ts:576` | OK |
| `chat.session.extras.updated` | ✓ | `cockpitStore.ts:162` | OK |
| `chat.session.pinned_updated` | ✓ | OK | |
| `chat.session.project.updated` | ✓ | OK | |
| `chat.compaction.*` | ✓ | `useChatStream.ts:586-658` | OK |
| **`Topics.ERROR` (generic)** | ✓ | **no subscriber anywhere** | Generic backend `ErrorEvent` vanishes silently |

### Findings

**d-1. `chat.session.restored` is not handled in the active chat view.**
*Severity: Medium. Confidence: High.*
`frontend/src/features/chat/ChatView.tsx:627` only subscribes to
`CHAT_SESSION_DELETED`. Two-tab scenario: deletion bounces tab 2 to
`/personas`; restore leaves tab 2 stranded. **Low-hanging fruit.**

**d-2. Generic `Topics.ERROR` events are dropped on the floor.**
*Severity: Medium. Confidence: High.*
`Topics.ERROR` declared in `frontend/src/core/types/events.ts:28` and
`shared/topics.py:21`, but no frontend code subscribes. Backend
`ErrorEvent` (per CLAUDE.md design contract) bypasses the entire UI.
**Low-hanging fruit.**

**d-3. `chat.client_tool.dispatch` has no timeout and no session/correlation gate.**
*Severity: High. Confidence: High.*
`frontend/src/features/code-execution/clientToolHandler.ts:38-44`. Backend
ships `timeout_ms` in the payload; the FE ignores it. A stuck sandbox
worker or hung MCP tool freezes the assistant turn forever — only recovery
is a hard reload. Also: dispatch for session B is executed while user is
in session A, because the handler does not filter by `event.payload.session_id`.

**d-4. `lastSequence` lives in `sessionStorage`, so multi-tab catchup is wrong.**
*Severity: Medium. Confidence: High.*
`frontend/src/core/store/eventStore.ts:5`. Each tab has its own
`lastSequence`; a freshly opened tab does not catch up via `since`
(`frontend/src/core/websocket/connection.ts:44-46` omits it when null).
Backend retains 24 h of streams so the data is there. Fix: `localStorage`
keyed per user, or `BroadcastChannel`.

**d-5. `CHAT_CONTENT_DELTA` is gated on Group, all other deltas on slot — split-brain.**
*Severity: Medium. Confidence: High.*
`frontend/src/features/chat/useChatStream.ts:104-115` (content delta uses
`getActiveGroupForSession(sessionId)`) vs `:116-242` (thinking, tool,
web-search use `getStreamFor(sessionId).correlationId`). Group-cancelled
but slot-active = content dropped, thinking/tool still flowing. Reverse
case also possible. Pick one rule, apply uniformly. **Low-hanging fruit.**

**d-6. Optimistic user message + `CHAT_MESSAGE_CREATED` race when `client_message_id` is dropped.**
*Severity: Medium. Confidence: Medium.*
`frontend/src/features/chat/useChatStream.ts:519-549`. If the backend ever
echoes the user message without a `client_message_id` (ChatGPT import
replay, future branch-fork synthetic message), the handler falls through
to `appendMessage`; the optimistic entry is still in the store; user sees
the message twice. Branching will create user messages without the
current tab's `client_message_id`.

**d-7. `session_id: sessionId ?? ''` on fallback append — wrong session id when guard loosens.**
*Severity: Low. Confidence: High.*
`frontend/src/features/chat/useChatStream.ts:539`. In practice the guard
at line 520 means this never fires today, but it is a foot-gun for any
future refactor. **Low-hanging fruit** (one-line).

**d-8. Many `as` casts on payloads, no schema validation.**
*Severity: Low. Confidence: High.* Across `useChatStream.ts`. Malformed
backend payloads crash at runtime. Larger lift — across-the-board change.

**d-9. `MessageList.tsx:209` uses `setInterval` polling for the slow-elapsed counter.**
*Severity: Low. Confidence: High.* Cosmetic counter only, but
`CLAUDE.md` says "Never poll for state". Either accept as UI-only or
switch to `requestAnimationFrame`.

**d-10. `autoscroll` MutationObserver fires per Shiki highlight pass.**
*Severity: Low. Confidence: Medium.*
`frontend/src/features/chat/useAutoScroll.ts:88-117`. Huge code blocks =
layout per frame. Longtask observer at `ChatView.tsx:1162` already proves
main-thread starvation. Throttle to one pin per 16 ms with a `lastPinAt`
ref.

**d-12. No interrupt/queue when user sends while assistant is streaming.**
*Severity: Low. Confidence: High.*
`frontend/src/features/chat/ChatInput.tsx:247`. Input is hard-disabled
mid-stream; only voice mode has barge. Branching will want per-branch
input enable/disable.

**d-13. `useChatStore.reset(sessionId)` + REST `getMessages` race.**
*Severity: Medium. Confidence: Medium.*
`frontend/src/core/store/chatStore.ts:543-548`,
`frontend/src/features/chat/ChatView.tsx:556-578`. Switching to a session
with a live stream can interleave the REST result with delayed echoes.
Buffer WS events for that session until the REST reconciliation lands.

**d-14. Edit gate uses `id.startsWith('optimistic-')` prefix sniffing.**
*Severity: Low. Confidence: High.*
`frontend/src/features/chat/MessageList.tsx:319`. Fragile. Replace with
an explicit `is_optimistic: boolean` on the DTO.

**d-15. `messagePillContents` cache keyed by message id; collisions if branches share ids.**
*Severity: Low. Confidence: Medium.*
`frontend/src/core/store/chatStore.ts:456-466, 476-487`. Backend must
enforce unique ids per branch; document the invariant.

**d-16. Compaction 90 s soft-timeout fires "running long" notification, but real `COMPLETED` 30 s later still fires the success toast.**
*Severity: Low. Confidence: High.*
`frontend/src/features/chat/ChatView.tsx:758-771`,
`frontend/src/features/chat/useChatStream.ts:627-636`. Confusing UX —
"running long" then "success" 30 s later.

### Branching-readiness gaps (work inventory)

These are not bugs — they are linear-history assumptions that need to be
extended for the tree model. Bundled here so the branching spec can
reference them as a single checklist.

1. `messages` is a flat array everywhere
   (`frontend/src/core/store/chatStore.ts:75`,
   `frontend/src/features/chat/MessageList.tsx:289`,
   `frontend/src/features/chat/useChatStream.ts:526`). Needs a "current
   branch path" projection or parent-pointer tree.
2. `messages[i - 1]` PTI-merge (`MessageList.tsx:348`) assumes positional
   adjacency.
3. `lastAssistantIdx` / `lastUserMessageId` (`MessageList.tsx:185, 220,
   263`) assume single linear stream.
4. `finishStreaming` appends to `s.messages` unconditionally for the
   active session (`chatStore.ts:434`).
5. `streamsBySession: Map<sessionId, slot>` may need to become
   `Map<sessionId+branchId, slot>` for concurrent branch streaming.
6. `activeSessionId` is the only "where are we" anchor — add
   `activeBranchPath` or equivalent.
7. `cancelGroupForSession(sid)` (`responseTaskGroup.ts`,
   `ChatView.tsx:744`) keyed only on session id.
8. `CHAT_MESSAGES_TRUNCATED` slices a linear list at a message id
   (`useChatStream.ts:552`, `chatStore.ts:456`). Tree truncation must drop
   a whole subtree.
9. Compaction `tail_start_message_id` is a single anchor. Per-branch
   compaction state needed.
10. Bookmarks / scroll-to-message resolve by `getElementById('msg-…')`
    (`ChatView.tsx:328`). DOM has only one node per id — collisions if
    branches share ids.
11. Edit/regenerate WS commands carry `session_id + message_id` only
    (`ChatView.tsx:1041, 1074`) — no branch identifier.
12. `appendCompactionCheckpoint` guards by active session
    (`chatStore.ts:519-521`) — branch within session not modelled.

---

## Open questions for Chris

Each agent flagged questions that need product/design decisions before
their findings can be acted on. Consolidated and de-duplicated:

### Branching model

1. **Schema:** true forks (sibling branches sharing a parent
   `message_id`, both alive forever, query by `branch_id`) or **checkpoint
   snapshots** (each branch is its own deep-copied `ChatSessionDocument`
   with a `forked_from` pointer)? The first is cleaner for storage but
   needs new query paths everywhere; the second matches existing
   `list_messages` with zero changes. **Recommended: separate session
   documents (clone-on-branch)** — it composes cleanly with existing
   compaction checkpoints, with the cost of more storage.
2. **Concurrent branch streaming** within one user session: allowed or
   serialised one-at-a-time?
3. **Branch from a compacted-out message:** disallow (mirror
   `edit_before_compact` guard) or allow with an explicit "your branch
   inherits the briefing" disclaimer?
4. **`messagePillContents` / `compaction_checkpoints`** on branch fork —
   share or clone?

### Reasoning / tool re-injection

5. **Branching with tool side effects:** if the user forks from a message
   where the assistant called `write_journal_entry`, do we (a) replay the
   recorded tool result (lying — entry already exists), (b) re-execute
   (duplicating), or (c) drop the tool call entirely from the replay?
6. **Anthropic signature persistence:** how long are signatures valid?
   A branch created weeks later may have the signature rejected. Accept
   the failure, or strip-and-retry?
7. **DSv4 / Kimi on Ollama Cloud:** soft-CoT class, but `thinking` is
   provider-emitted. `replay_reasoning` should be `False` there too?
8. **Effort persistence on branches:** if we replay thinking, does the
   original turn's `reasoning_effort` survive, or does the branch's
   current setting win?
9. **Tool-result truncation:** big web_fetch results (20k chars) — do we
   want a "tool-result summary on N+2" policy? Out of scope for branching
   itself, but worth flagging now.

### Context handling

10. **`save_fn` failure mid-stream:** (a) write a "broken" placeholder
    with captured content, (b) retry in a background task, or (c) fire
    `ChatStreamErrorEvent` and tell user to regenerate?
11. **Per-adapter token reconciliation:** is provider-reported
    `input_tokens` the new "truth" between turns, or do we want both
    numbers persisted and shown side-by-side for transparency?
12. **`list_messages` 5000 cap:** has anyone seen a session approach this
    yet? Determines whether a-5 is urgent.
13. **Aborted user prompts:** abort-before-delta deletes the user
    message; abort-after-delta keeps it. Should branching treat both the
    same (preserve user message + allow regenerate)?

### Compaction

14. **Auto-Mode + discovery dialog (spec §6.0/§6.5):** in scope for
    v0.2.0? No implementation found.
15. **Reversibility (c-14):** "rollback last compaction" for v0.2.0, or
    accept "start a new session" as the recovery path?
16. **Are concurrent compactions across multiple sessions intentional?**
    Lock is per-session; a power user could compact 3 sessions in
    parallel. With c-3 unfixed this is a budget DoS.
17. **`compaction_source_too_large`:** should we offer a two-stage
    hierarchical compaction (spec §10) before declaring v0.2.0 ready, or
    is "switch to a larger model" acceptable?

### Frontend

18. **`lastSequence` per tab (d-4):** by design (incognito-resilient) or
    accidental? If by design, multi-tab catchup gap is acceptable.
19. **Want a generic `Topics.ERROR` toast subscriber added** at app-shell
    level (d-2)?
20. **Client-tool dispatch timeout (d-3):** expiry surfaces as a
    stream-error event, or a silent tool-result error?

---

## Low-Hanging Fruits

Items I can land autonomously: each is < 150 LoC, semantically clear,
needs no design discussion. **Sorted by recommended order: lock-honouring
first (because c-1/c-7 fixes are prerequisites for several others), then
correctness, then ergonomics.**

### Backend — safety & correctness

1. ~~**Honour the compaction lock in `chat.send` / `chat.edit` / `chat.regenerate`** (c-1, c-7).~~ **(done)**
   `backend/modules/chat/_handlers_ws.py`. New helpers
   `_compaction_lock_held()` and `_emit_stream_error()`; called at the
   top of each handler before persistence. Emits
   `compaction_in_progress` recoverable error.
2. ~~**Wrap compaction-trigger post-acquire body in try/except + delete-lock-on-failure** (c-4).~~ **(done)**
   `handle_chat_compaction_request` now uses `lock_key` /
   `lock_handed_off` sentinels; the outer `except` releases the lock
   when an unexpected exception fires before `submit_job` succeeds.
3. ~~**Wrap `save_fn` in try/except so `ChatStreamEndedEvent` always fires** (a-1 partial).~~ **(done)**
   `backend/modules/chat/_inference.py`. On `save_fn` failure: logs,
   emits `ChatStreamErrorEvent(error_code="persistence_failed")`, falls
   through to terminal `ChatStreamEndedEvent` with `status="error"`.
   New test file `test_inference_save_failure.py` (3 tests).
4. ~~**Move `context_window_full` pre-flight before `repo.save_message`** (a-7).~~ **(done)**
   New helper `_is_context_window_full()` in `_handlers_ws.py`; fires
   in `handle_chat_send` right after `token_count`, before PTI lookup
   and `save_message`. Uses caller-supplied `correlation_id`.
5. ~~**`list_messages` tail variant + warning when 5000 cap is hit** (a-5).~~ **(done)**
   `backend/modules/chat/_repository.py`. Added `list_messages_tail()`;
   orchestrator history-load now uses it. Old `list_messages` warns
   when the cap is hit. New test file `test_list_messages_tail.py`
   (3 tests).
6. ~~**Wire SG-002 budget into compaction handler** (c-3).~~ **(done)**
   `backend/jobs/handlers/_chat_compaction.py`. Prompt + transcript
   built up front; `check_and_reserve_budget()` reserves;
   `record_handler_tokens()` records real `StreamDone.input_tokens` /
   `output_tokens` after the call. `UnrecoverableJobError` surfaces
   as `budget_exceeded` (recoverable=False).
7. ~~**Add `tool_call_id` to Ollama tool translation** (b-4).~~ **(done)**
   `backend/modules/llm/_adapters/_ollama_http.py:148-149`. Three-line
   change + test in `test_ollama_http.py`.
8. ~~**Compaction job: always use `checkpoints[-1]`, treat payload as sanity check** (c-11).~~ **(done)**
   `backend/jobs/handlers/_chat_compaction.py:81-102`. Mismatch is
   logged but not fatal; the session document is the source of truth.
9. ~~**Re-compute post-compact metrics from the assembled system prompt** (c-5).~~ **(done)**
   `backend/jobs/handlers/_chat_compaction.py`. Calls `assemble(...)`
   with the new `compact_markdown`; `count_tokens(system_prompt)` is
   added to `tail_token_count` for the persisted metric. Falls back
   to the legacy estimate if assembly fails.
10. ~~**Decide compaction handler error semantics** (c-2).~~ **(done)**
    Removed dead config — `backend/jobs/_registry.py`: `max_retries=0`,
    `notify_error=False`. Retries are user-driven via the Retry toast;
    the handler captures all failures and emits
    `CHAT_COMPACTION_FAILED` itself.

### Backend — ergonomics

11. ~~**Surface attachment / image / artefact metadata in compaction transcript** (c-6).~~ **(done)**
    `backend/modules/chat/_compaction.py:233-265`. Appends
    `[Attachments: …]` / `[Generated: …]` / `[Artefacts: …]` lines per
    message based on `attachment_refs`, `image_refs`, `artefact_refs`.
12. ~~**Bump compaction validation-retry temperature to 0.5** (c-13).~~ **(done)**
    `backend/jobs/handlers/_chat_compaction.py`. Attempt 1 stays at
    0.3; attempt 2 uses 0.5 with the reminder appendix.
13. ~~**Track separate `total_session_tokens` and `tokens_actually_sent` in `ChatStreamEndedEvent`** (a-11).~~ **(done)**
    `shared/events/chat.py` — both fields added as optional ints
    (additive, no breaking change to existing `context_used_tokens`).
    Orchestrator captures the pair-selection result so it can emit
    both numbers. Frontend `ContextStatusPill` shows the second line
    only when divergence > 5 % to avoid pill-noise. Backend test
    `test_inference_token_metrics.py` (2 tests) covers the additive
    contract.

### Frontend — safety & correctness

14. ~~**Subscribe `CHAT_SESSION_RESTORED` in ChatView** (d-1).~~ **(done)**
    `frontend/src/features/chat/ChatView.tsx`. Sibling to the
    `CHAT_SESSION_DELETED` subscription; if the restored session is
    active, refetches session metadata via `chatApi.getSession`.
15. ~~**App-shell subscriber for generic `Topics.ERROR`** (d-2).~~ **(done)**
    New file `frontend/src/core/websocket/genericErrorHandler.ts`,
    wired in `frontend/src/App.tsx`. Routes `user_message` to an
    error toast via `useNotificationStore`. Title flips between
    "Something went wrong" (recoverable) and "Error" (final).
16. ~~**Enforce `timeout_ms` and session-id filter in client-tool dispatch** (d-3).~~ **(done)**
    `frontend/src/features/code-execution/clientToolHandler.ts`. Added
    `raceWithTimeout()` around the integration-plugin path; on
    timeout sends `client_tool_timeout` in the tool-result shape.
    Session-mismatch: logs a structured warning but still executes,
    because dropping the call would orphan the server's tool turn.
    Tests added under `__tests__/clientToolHandler.test.ts`.
17. ~~**Switch `lastSequence` to `localStorage` keyed per user** (d-4).~~ **(done)**
    `frontend/src/core/store/eventStore.ts`. Per-user key
    `chatsune:lastSequence:{userId}`; in-memory fallback when no user.
    `clearPersistedSequenceFor()` invoked by `logoutCoordinator` and
    `useAuth.deleteAccount`. `attachAuthListener()` uses bounded
    `setTimeout(0)` retry to bridge the eventStore↔authStore import
    cycle without the original busy-wait trap. 5 new tests in
    `eventStore.test.ts`.
18. ~~**Unify delta gating on slot-correlationId for all deltas** (d-5).~~ **(done)**
    `frontend/src/features/chat/useChatStream.ts`. `CHAT_CONTENT_DELTA`
    now gates on `slot.correlationId === event.correlation_id` like
    the other deltas. Tests added in `useChatStream.gating.test.ts`.
19. ~~**Fix `session_id ?? ''` fallback to `p.session_id as string`** (d-7).~~ **(done)**
    `frontend/src/features/chat/useChatStream.ts:548`. One-line fix
    in the `CHAT_MESSAGE_CREATED` append-fallback path.

### Frontend — ergonomics

20. ~~**Raise compaction soft-timeout to 150 s** (c-8).~~ **(done)**
    `frontend/src/features/chat/ChatView.tsx:752-775`. `90_000` →
    `150_000` ms (backend `execution_timeout_seconds=120` + 30 s buffer).
21. ~~**Suppress success toast when the 90 s soft-timeout has already fired** (d-16).~~ **(done)**
    `chatStore.ts` gains `compactionTimedOutCorrelationIds` set with
    `markCompactionTimedOut` / `consumeCompactionTimedOut`. The
    150-s timer marks the in-flight correlation; the COMPLETED handler
    consumes and skips the toast. 4 store tests + handler test.
22. ~~**Replace `optimistic-` prefix sniff with explicit `is_optimistic` flag** (d-14).~~ **(done)**
    `frontend/src/core/api/chat.ts` adds optional `is_optimistic?:
    boolean` to `ChatMessageDto`. `ChatView.insertOptimisticAndSend`
    sets it; `useChatStream` clears it on `CHAT_MESSAGE_CREATED`.
    Consumers `MessageList.tsx:335` and `ChatView.handleEdit` now
    gate on the flag instead of `id.startsWith('optimistic-')`. The
    id prefix itself stays — it is still the swap key.
23. ~~**Throttle autoscroll pin to one per 16 ms** (d-10).~~ **(done)**
    `frontend/src/features/chat/useAutoScroll.ts:48-118`. Added
    `lastPinAtRef`; inside the rAF callback, skip if elapsed < 16 ms.
24. ~~**Document `messagePillContents` unique-id-per-branch invariant** (d-15).~~ **(done)**
    `frontend/src/core/store/chatStore.ts:87-95`. JSDoc INVARIANT block
    noting the cache assumption; branching must preserve unique ids.

### Excluded from "autonomous" — design discussion required

- a-2 `select_message_pairs` rewrite — algorithm change, deserves review.
- a-3 Two-tab race full fix — multiple valid strategies (lock-everything
  vs cancel-then-skip-save), Chris should pick.
- a-4 `session_seq` schema change + backfill migration.
- a-6 / c-15 Per-adapter token reconciliation — strategic choice.
- a-8 Reconnect mid-stream snapshot — needs runner state exposure.
- a-9 Schema change for branching (the headline feature itself).
- b-1, b-2, b-3 DTO extension for `CompletionMessage.thinking_blocks` and
  history expansion — bundled work.
- c-9, c-10 Branching ↔ compaction composition.
- d-6 Optimistic dedup-by-content fallback.
- d-13 `reset` + REST race buffering.

---

## Recommended sequencing

1. **Land the safety low-hanging fruits first** (items 1-7 above) — they
   close real correctness windows that exist today and are independent of
   branching.
2. **Make the open-question calls** (numbered list above). Without them
   the design work cannot start.
3. **Land the structural prerequisites:**
   - `CompletionMessage.thinking_blocks` + history expansion (b-1, b-2, b-3)
   - `session_seq` migration if branching uses ordered messages (a-4)
   - Per-branch `compaction_checkpoints` if clone-on-branch is rejected
     in favour of shared sessions (c-10)
4. **Then design + implement branching.**
5. **Ergonomic fruits** (items 11-13, 20-24) can land in parallel any time.
