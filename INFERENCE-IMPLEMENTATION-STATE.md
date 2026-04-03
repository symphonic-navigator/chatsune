# Inference Implementation — Current State

Last updated: 2026-04-03 (Phase 2 complete)

---

## BEFORE YOU START

1. **Check parallel session output:** The system-wide system prompt
   (`global_system_prompt` via `app_settings`) was being implemented in a
   parallel session. Verify the settings infrastructure is in place and aligned
   with the design spec before implementing the system prompt assembler.

2. **Review the design spec:** Read through
   `docs/superpowers/specs/2026-04-03-context-management-and-chat-features-design.md`
   to confirm it still matches your intent. Pay particular attention to the
   system prompt assembly section (Section 1) — it depends on whatever the
   parallel session built.

3. **Check FOR_LATER.md** is still accurate.

---

## Phase 1 — COMPLETE (14 commits on master)

Minimal streaming loop: Ollama Cloud → WebSocket → User.

### What was built

| Component | Files | Status |
|-----------|-------|--------|
| Shared inference DTOs | `shared/dtos/inference.py` | Done |
| Provider stream events | `backend/modules/llm/_adapters/_events.py` | Done |
| BaseAdapter abstract method | `backend/modules/llm/_adapters/_base.py` | Done |
| Ollama Cloud streaming | `backend/modules/llm/_adapters/_ollama_cloud.py` | Done |
| LLM module public API | `backend/modules/llm/__init__.py` | Done |
| Chat shared contracts | `shared/dtos/chat.py`, `shared/events/chat.py`, `shared/topics.py` | Done |
| Chat repository + models | `backend/modules/chat/_repository.py`, `_models.py` | Done |
| Chat REST handlers | `backend/modules/chat/_handlers.py` | Done |
| InferenceRunner | `backend/modules/chat/_inference.py` | Done |
| EventBus fan-out rules | `backend/ws/event_bus.py` | Done |
| WebSocket router dispatch | `backend/ws/router.py`, `backend/modules/chat/__init__.py` | Done |
| Persona public API | `backend/modules/persona/__init__.py` — `get_persona()` | Done |

### Test coverage

- 36 unit tests passing (skip integration tests without Docker)
- Test files: `test_shared_inference_contracts.py`, `test_provider_stream_events.py`,
  `test_ollama_cloud_streaming.py`, `test_shared_chat_contracts.py`,
  `test_inference_runner.py`, `test_chat_repository.py`, `test_chat_sessions.py`

### Known limitations (remaining after Phase 2)

- No tool calls
- No attachments (images, files)
- No memory system
- No session cloning
- No "Synopsis & Continue" for full context windows

---

## Phase 2 — COMPLETE

Design spec: `docs/superpowers/specs/2026-04-03-context-management-and-chat-features-design.md`

### What was built

| Component | Files | Status |
|-----------|-------|--------|
| tiktoken dependency | `backend/pyproject.toml` | Done |
| Token counter | `backend/modules/chat/_token_counter.py` | Done |
| Prompt sanitiser | `backend/modules/chat/_prompt_sanitiser.py` | Done |
| Settings public API | `backend/modules/settings/__init__.py` — `get_setting()` | Done |
| User about_me field | `backend/modules/user/_repository.py`, `_handlers.py`, `__init__.py` | Done |
| LLM context window API | `backend/modules/llm/__init__.py` — `get_model_context_window()` | Done |
| Prompt assembler | `backend/modules/chat/_prompt_assembler.py` | Done |
| Context window manager | `backend/modules/chat/_context.py` | Done |
| Edit/regenerate events | `shared/events/chat.py`, `shared/topics.py`, `backend/ws/event_bus.py` | Done |
| Repository query methods | `backend/modules/chat/_repository.py` | Done |
| Chat module refactor | `backend/modules/chat/__init__.py` — `_run_inference`, edit, regenerate | Done |
| InferenceRunner update | `backend/modules/chat/_inference.py` — context params | Done |
| WebSocket router | `backend/ws/router.py` — `chat.edit`, `chat.regenerate` dispatch | Done |

### Key design decisions

- **No rolling window** — preserves prompt cache prefix, no silent data loss
- **Hard block at 80%** — future "Synopsis & Continue" replaces this (FOR_LATER.md)
- **Linear edit** — truncate, no branching
- **cl100k_base** — pessimistic but safe token counting

---

## Deferred features

See `FOR_LATER.md` for full list. Key items:
- Context Synopsis & Continue (the "geiler als die anderen" feature)
- Tool calls (server-side + client-side)
- Memory system (tool-based, replaces RAG)
- Attachments
- Additional providers
- Session cloning
