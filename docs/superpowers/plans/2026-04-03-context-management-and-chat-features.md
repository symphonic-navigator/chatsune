# Context Management & Chat Features — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete the inference pipeline with proper token counting, system prompt assembly, context window management, context ampel, message edit, and message regenerate.

**Architecture:** Six new internal modules in `backend/modules/chat/` handle token counting (`_token_counter.py`), prompt sanitisation (`_prompt_sanitiser.py`), prompt assembly (`_prompt_assembler.py`), and context selection (`_context.py`). The existing `handle_chat_send` is refactored to extract a shared `_run_inference` function that all three chat operations (send, edit, regenerate) converge on. New repository methods support truncation, update, and deletion. New shared events and topics support edit/regenerate flows.

**Tech Stack:** Python, FastAPI, Pydantic v2, tiktoken (cl100k_base), MongoDB (motor), Redis

**Design Spec:** `docs/superpowers/specs/2026-04-03-context-management-and-chat-features-design.md`

---

## File Map

### New Files

| File | Responsibility |
|------|---------------|
| `backend/modules/chat/_token_counter.py` | tiktoken wrapper, module-level cl100k_base singleton, `count_tokens(text) -> int` |
| `backend/modules/chat/_prompt_sanitiser.py` | Strip reserved XML tags from user-controlled content |
| `backend/modules/chat/_prompt_assembler.py` | 4-layer XML assembly (`assemble()`) and preview (`assemble_preview()`) |
| `backend/modules/chat/_context.py` | Budget calculation, pair-based backread, ampel status |
| `tests/test_token_counter.py` | Tests for token counter |
| `tests/test_prompt_sanitiser.py` | Tests for prompt sanitiser |
| `tests/test_prompt_assembler.py` | Tests for prompt assembler |
| `tests/test_context_manager.py` | Tests for context window selection and ampel |
| `tests/test_chat_edit.py` | Tests for message edit flow |
| `tests/test_chat_regenerate.py` | Tests for message regenerate flow |

### Modified Files

| File | Change |
|------|--------|
| `backend/pyproject.toml` | Add `tiktoken` dependency |
| `shared/topics.py` | Add `CHAT_MESSAGES_TRUNCATED`, `CHAT_MESSAGE_UPDATED`, `CHAT_MESSAGE_DELETED` |
| `shared/events/chat.py` | Add `ChatMessagesTruncatedEvent`, `ChatMessageUpdatedEvent`, `ChatMessageDeletedEvent`, add `context_fill_percentage` to `ChatStreamEndedEvent` |
| `backend/modules/settings/__init__.py` | Add `get_setting()` public API function |
| `backend/modules/user/_repository.py` | Add `update_about_me()` and `get_about_me()` methods |
| `backend/modules/user/_handlers.py` | Add `PATCH /api/users/me/about-me` and `GET /api/users/me/about-me` endpoints |
| `backend/modules/user/__init__.py` | Expose `get_user_about_me()` |
| `shared/dtos/auth.py` | Add `UpdateAboutMeDto` |
| `backend/modules/llm/__init__.py` | Expose `get_model_context_window()` |
| `backend/modules/chat/_repository.py` | Add `delete_messages_after()`, `update_message_content()`, `get_last_message()` |
| `backend/modules/chat/__init__.py` | Refactor: extract `_run_inference()`, add `handle_chat_edit`, `handle_chat_regenerate` |
| `backend/modules/chat/_inference.py` | Accept `context_status` and `context_fill_percentage` params |
| `backend/ws/router.py` | Add `chat.edit` and `chat.regenerate` dispatch |
| `backend/ws/event_bus.py` | Add fan-out rules for new chat events |

---

## Task 1: Add tiktoken Dependency

**Files:**
- Modify: `backend/pyproject.toml`

- [ ] **Step 1: Add tiktoken to dependencies**

In `backend/pyproject.toml`, add `tiktoken` to the `dependencies` list:

```toml
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.34",
    "pydantic>=2.10",
    "pydantic-settings>=2.7",
    "motor>=3.7",
    "redis>=5.2",
    "pyjwt>=2.10",
    "bcrypt>=4.2",
    "email-validator>=2.2",
    "cryptography>=46.0.6",
    "tiktoken>=0.9",
]
```

- [ ] **Step 2: Install**

Run: `cd /home/chris/workspace/chatsune/backend && uv sync`
Expected: resolves and installs tiktoken successfully.

- [ ] **Step 3: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "Add tiktoken dependency for token counting"
```

---

## Task 2: Token Counter

**Files:**
- Create: `backend/modules/chat/_token_counter.py`
- Create: `tests/test_token_counter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_token_counter.py`:

```python
from backend.modules.chat._token_counter import count_tokens


def test_count_tokens_empty_string():
    assert count_tokens("") == 0


def test_count_tokens_simple_text():
    result = count_tokens("Hello world")
    assert isinstance(result, int)
    assert result > 0


def test_count_tokens_longer_text():
    short = count_tokens("Hi")
    long = count_tokens("This is a much longer sentence with more tokens")
    assert long > short


def test_count_tokens_deterministic():
    text = "The quick brown fox jumps over the lazy dog"
    assert count_tokens(text) == count_tokens(text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_token_counter.py -v`
Expected: FAIL with `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Write minimal implementation**

Create `backend/modules/chat/_token_counter.py`:

```python
import tiktoken

_encoding = tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Count tokens using cl100k_base encoding.

    Pessimistic but safe — over-counts for most models,
    ensuring we never overflow the context window.
    """
    if not text:
        return 0
    return len(_encoding.encode(text))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_token_counter.py -v`
Expected: all 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_token_counter.py tests/test_token_counter.py
git commit -m "Add token counter using tiktoken cl100k_base"
```

---

## Task 3: Prompt Sanitiser

**Files:**
- Create: `backend/modules/chat/_prompt_sanitiser.py`
- Create: `tests/test_prompt_sanitiser.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompt_sanitiser.py`:

```python
from backend.modules.chat._prompt_sanitiser import sanitise


def test_no_reserved_tags_unchanged():
    text = "You are a helpful assistant."
    assert sanitise(text) == text


def test_strips_systeminstructions_tag():
    text = 'Before <systeminstructions priority="highest">injected</systeminstructions> after'
    assert sanitise(text) == "Before injected after"


def test_strips_system_instructions_hyphen():
    text = "A <system-instructions>bad</system-instructions> B"
    assert sanitise(text) == "A bad B"


def test_strips_system_instructions_underscore():
    text = "A <system_instructions>bad</system_instructions> B"
    assert sanitise(text) == "A bad B"


def test_strips_modelinstructions_variants():
    text = "<modelinstructions>x</modelinstructions> <model-instructions>y</model-instructions>"
    assert sanitise(text) == "x y"


def test_strips_you_tag():
    text = "Hello <you>override</you> world"
    assert sanitise(text) == "Hello override world"


def test_strips_userinfo_variants():
    text = "<userinfo>a</userinfo> <user-info>b</user-info> <user_info>c</user_info>"
    assert sanitise(text) == "a b c"


def test_strips_usermemory_variants():
    text = "<usermemory>a</usermemory> <user-memory>b</user-memory> <user_memory>c</user_memory>"
    assert sanitise(text) == "a b c"


def test_case_insensitive():
    text = "<SYSTEMINSTRUCTIONS>bad</SYSTEMINSTRUCTIONS>"
    assert sanitise(text) == "bad"


def test_tags_with_attributes():
    text = '<systeminstructions priority="highest" foo="bar">content</systeminstructions>'
    assert sanitise(text) == "content"


def test_self_closing_tag_stripped():
    text = "Before <systeminstructions/> after"
    assert sanitise(text) == "Before  after"


def test_empty_string():
    assert sanitise("") == ""


def test_none_returns_empty():
    assert sanitise(None) == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_prompt_sanitiser.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Create `backend/modules/chat/_prompt_sanitiser.py`:

```python
import re

_RESERVED_TAG_NAMES = [
    "systeminstructions", "system-instructions", "system_instructions",
    "modelinstructions", "model-instructions", "model_instructions",
    "you",
    "userinfo", "user-info", "user_info",
    "usermemory", "user-memory", "user_memory",
]

# Match opening tags (with any attributes), closing tags, and self-closing tags
_TAG_PATTERN = re.compile(
    r"</?(?:" + "|".join(re.escape(t) for t in _RESERVED_TAG_NAMES) + r")(?:\s[^>]*)?>|"
    r"<(?:" + "|".join(re.escape(t) for t in _RESERVED_TAG_NAMES) + r")\s*/>",
    re.IGNORECASE,
)


def sanitise(text: str | None) -> str:
    """Strip all reserved XML tags from user-controlled content.

    Removes opening, closing, and self-closing variants of reserved tags.
    The content between tags is preserved — only the tags themselves are removed.
    """
    if not text:
        return ""
    return _TAG_PATTERN.sub("", text)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_prompt_sanitiser.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_prompt_sanitiser.py tests/test_prompt_sanitiser.py
git commit -m "Add prompt sanitiser to strip reserved XML tags"
```

---

## Task 4: Settings Module — `get_setting()` Public API

**Files:**
- Modify: `backend/modules/settings/__init__.py`

- [ ] **Step 1: Write the failing test**

Add to a new file `tests/test_settings_get_setting.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


async def test_get_setting_returns_value():
    mock_repo = AsyncMock()
    mock_repo.find.return_value = {"_id": "system_prompt", "value": "Be helpful", "updated_at": None, "updated_by": None}

    with patch("backend.modules.settings.SettingsRepository", return_value=mock_repo), \
         patch("backend.modules.settings.get_db"):
        from backend.modules.settings import get_setting
        result = await get_setting("system_prompt")
        assert result == "Be helpful"


async def test_get_setting_returns_none_when_missing():
    mock_repo = AsyncMock()
    mock_repo.find.return_value = None

    with patch("backend.modules.settings.SettingsRepository", return_value=mock_repo), \
         patch("backend.modules.settings.get_db"):
        from backend.modules.settings import get_setting
        result = await get_setting("nonexistent")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_settings_get_setting.py -v`
Expected: FAIL — `get_setting` not importable

- [ ] **Step 3: Write minimal implementation**

Modify `backend/modules/settings/__init__.py` to add the `get_setting` function:

```python
"""Settings module -- platform-wide admin-managed configuration.

Public API: import only from this file.
"""

from backend.modules.settings._handlers import router
from backend.modules.settings._repository import SettingsRepository
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the settings module collections."""
    await SettingsRepository(db).create_indexes()


async def get_setting(key: str) -> str | None:
    """Return the value for a setting key, or None if not set."""
    repo = SettingsRepository(get_db())
    doc = await repo.find(key)
    if doc is None:
        return None
    return doc["value"]


__all__ = ["router", "init_indexes", "SettingsRepository", "get_setting"]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_settings_get_setting.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/settings/__init__.py tests/test_settings_get_setting.py
git commit -m "Add get_setting() public API to settings module"
```

---

## Task 5: User Module — `about_me` Field

**Files:**
- Modify: `backend/modules/user/_repository.py`
- Modify: `backend/modules/user/_handlers.py`
- Modify: `backend/modules/user/__init__.py`
- Modify: `shared/dtos/auth.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_user_about_me.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch


async def test_get_user_about_me_returns_value():
    mock_repo = AsyncMock()
    mock_repo.find_by_id.return_value = {"_id": "user-1", "about_me": "I like cats"}

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("user-1")
        assert result == "I like cats"


async def test_get_user_about_me_returns_none_when_missing():
    mock_repo = AsyncMock()
    mock_repo.find_by_id.return_value = {"_id": "user-1"}

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("user-1")
        assert result is None


async def test_get_user_about_me_returns_none_when_user_not_found():
    mock_repo = AsyncMock()
    mock_repo.find_by_id.return_value = None

    with patch("backend.modules.user.UserRepository", return_value=mock_repo), \
         patch("backend.modules.user.get_db"):
        from backend.modules.user import get_user_about_me
        result = await get_user_about_me("nonexistent")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_user_about_me.py -v`
Expected: FAIL — `get_user_about_me` not importable

- [ ] **Step 3: Add `UpdateAboutMeDto` to shared DTOs**

Add to `shared/dtos/auth.py` (at the end of the file):

```python
class UpdateAboutMeDto(BaseModel):
    about_me: str | None = None
```

- [ ] **Step 4: Add repository methods**

Add to `backend/modules/user/_repository.py` (inside the `UserRepository` class, after the existing `count` method):

```python
    async def update_about_me(self, user_id: str, about_me: str | None) -> dict | None:
        fields = {"about_me": about_me, "updated_at": datetime.now(UTC)}
        await self._collection.update_one({"_id": user_id}, {"$set": fields})
        return await self.find_by_id(user_id)

    async def get_about_me(self, user_id: str) -> str | None:
        doc = await self.find_by_id(user_id)
        if doc is None:
            return None
        return doc.get("about_me")
```

- [ ] **Step 5: Add REST endpoints**

Add to `backend/modules/user/_handlers.py` (after the `change_password` endpoint, before `# --- User Management ---`):

```python
# --- User Profile ---


@router.get("/users/me/about-me")
async def get_about_me(user: dict = Depends(get_current_user)):
    repo = _user_repo()
    about_me = await repo.get_about_me(user["sub"])
    return {"about_me": about_me}


@router.patch("/users/me/about-me")
async def update_about_me(
    body: UpdateAboutMeDto,
    user: dict = Depends(get_current_user),
):
    repo = _user_repo()
    await repo.update_about_me(user["sub"], body.about_me)
    return {"about_me": body.about_me}
```

Also add the import at the top of `_handlers.py`:

```python
from shared.dtos.auth import (
    # ... existing imports ...
    UpdateAboutMeDto,
)
```

- [ ] **Step 6: Add `get_user_about_me()` to module public API**

Modify `backend/modules/user/__init__.py`:

```python
"""User module — auth, user management, audit log.

Public API: import only from this file.
"""

from backend.modules.user._audit import AuditRepository
from backend.modules.user._auth import (
    create_access_token,
    decode_access_token,
    generate_refresh_token,
    generate_session_id,
)
from backend.modules.user._handlers import router
from backend.modules.user._refresh import RefreshTokenStore
from backend.modules.user._repository import UserRepository
from backend.config import settings
from backend.database import get_db


async def init_indexes(db) -> None:
    """Create MongoDB indexes for user module collections."""
    await UserRepository(db).create_indexes()
    await AuditRepository(db).create_indexes()


async def perform_token_refresh(refresh_token: str, redis) -> dict | None:
    """Rotate a refresh token and return new token data, or None if invalid."""
    store = RefreshTokenStore(redis)
    data = await store.consume(refresh_token)
    if data is None:
        return None

    repo = UserRepository(get_db())
    user = await repo.find_by_id(data["user_id"])
    if not user or not user["is_active"]:
        return None

    session_id = data["session_id"]
    access_token = create_access_token(
        user_id=user["_id"],
        role=user["role"],
        session_id=session_id,
        must_change_password=user["must_change_password"],
    )
    new_refresh_token = generate_refresh_token()
    await store.store(new_refresh_token, user_id=user["_id"], session_id=session_id)

    return {
        "access_token": access_token,
        "refresh_token": new_refresh_token,
        "expires_in": settings.jwt_access_token_expire_minutes * 60,
    }


async def get_user_about_me(user_id: str) -> str | None:
    """Return the user's about_me text, or None if not set."""
    repo = UserRepository(get_db())
    return await repo.get_about_me(user_id)


__all__ = [
    "router", "init_indexes", "perform_token_refresh",
    "decode_access_token", "get_user_about_me",
]
```

- [ ] **Step 7: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_user_about_me.py -v`
Expected: all 3 tests PASS

- [ ] **Step 8: Commit**

```bash
git add shared/dtos/auth.py backend/modules/user/_repository.py backend/modules/user/_handlers.py backend/modules/user/__init__.py tests/test_user_about_me.py
git commit -m "Add about_me field to user module with REST endpoints"
```

---

## Task 6: LLM Module — `get_model_context_window()` Public API

**Files:**
- Modify: `backend/modules/llm/__init__.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_llm_context_window.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch
from shared.dtos.llm import ModelMetaDto


def _make_model(provider_id: str, model_id: str, context_window: int) -> ModelMetaDto:
    return ModelMetaDto(
        provider_id=provider_id,
        model_id=model_id,
        display_name=model_id,
        context_window=context_window,
        supports_reasoning=False,
        supports_vision=False,
        supports_tool_calls=False,
    )


async def test_get_model_context_window_found():
    models = [
        _make_model("ollama_cloud", "llama3.2", 131072),
        _make_model("ollama_cloud", "mistral", 32768),
    ]

    with patch("backend.modules.llm.get_models", return_value=models) as mock_get, \
         patch("backend.modules.llm.get_db"), \
         patch("backend.modules.llm.get_redis"):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("ollama_cloud", "llama3.2")
        assert result == 131072


async def test_get_model_context_window_not_found():
    models = [_make_model("ollama_cloud", "mistral", 32768)]

    with patch("backend.modules.llm.get_models", return_value=models) as mock_get, \
         patch("backend.modules.llm.get_db"), \
         patch("backend.modules.llm.get_redis"):
        from backend.modules.llm import get_model_context_window
        result = await get_model_context_window("ollama_cloud", "nonexistent")
        assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_llm_context_window.py -v`
Expected: FAIL — `get_model_context_window` not importable

- [ ] **Step 3: Write minimal implementation**

Modify `backend/modules/llm/__init__.py` — add the import of `get_models` and `get_redis`, then add the function:

Add these imports at the top:

```python
from backend.modules.llm._metadata import get_models
from backend.database import get_db, get_redis
```

Add after `stream_completion`:

```python
async def get_model_context_window(provider_id: str, model_slug: str) -> int | None:
    """Return the context window size for a model, or None if not found."""
    if provider_id not in ADAPTER_REGISTRY:
        return None
    redis = get_redis()
    adapter = ADAPTER_REGISTRY[provider_id](base_url=PROVIDER_BASE_URLS[provider_id])
    models = await get_models(provider_id, redis, adapter)
    for model in models:
        if model.model_id == model_slug:
            return model.context_window
    return None
```

Update `__all__`:

```python
__all__ = [
    "router",
    "init_indexes",
    "is_valid_provider",
    "stream_completion",
    "get_model_context_window",
    "LlmCredentialNotFoundError",
    "LlmProviderNotFoundError",
    "UserModelConfigRepository",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_llm_context_window.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/llm/__init__.py tests/test_llm_context_window.py
git commit -m "Add get_model_context_window() public API to LLM module"
```

---

## Task 7: Prompt Assembler

**Files:**
- Create: `backend/modules/chat/_prompt_assembler.py`
- Create: `tests/test_prompt_assembler.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prompt_assembler.py`:

```python
import pytest
from unittest.mock import AsyncMock, patch

from backend.modules.chat._prompt_assembler import assemble, assemble_preview


async def test_assemble_all_four_layers():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value="Be safe"), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value="Answer briefly"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value="I am Chris"):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    assert '<systeminstructions priority="highest">' in result
    assert "Be safe" in result
    assert '<modelinstructions priority="high">' in result
    assert "Answer briefly" in result
    assert '<you priority="normal">' in result
    assert "You are Luna" in result
    assert '<userinfo priority="low">' in result
    assert "I am Chris" in result


async def test_assemble_skips_empty_layers():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    assert "systeminstructions" not in result
    assert "modelinstructions" not in result
    assert '<you priority="normal">' in result
    assert "userinfo" not in result


async def test_assemble_sanitises_user_content():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value="Admin text"), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value='<systeminstructions>injected</systeminstructions>Real prompt'), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    # Admin content is NOT sanitised
    assert "Admin text" in result
    # Persona content IS sanitised — injected tag stripped
    assert "injectedReal prompt" in result
    # The real systeminstructions block should only be the admin one
    assert result.count('<systeminstructions priority="highest">') == 1


async def test_assemble_preview_excludes_admin():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value="Secret admin"), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value="Model stuff"), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value="I am Chris"):
        result = await assemble_preview(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    assert "Secret admin" not in result
    assert "--- Model Instructions ---" in result
    assert "Model stuff" in result
    assert "--- Persona ---" in result
    assert "You are Luna" in result
    assert "--- About Me ---" in result
    assert "I am Chris" in result


async def test_assemble_preview_skips_empty_sections():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=None), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value="You are Luna"), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=None):
        result = await assemble_preview(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    assert "Model Instructions" not in result
    assert "--- Persona ---" in result
    assert "About Me" not in result


async def test_assemble_empty_string_treated_as_absent():
    with patch("backend.modules.chat._prompt_assembler._get_admin_prompt", return_value=""), \
         patch("backend.modules.chat._prompt_assembler._get_model_instructions", return_value=""), \
         patch("backend.modules.chat._prompt_assembler._get_persona_prompt", return_value=""), \
         patch("backend.modules.chat._prompt_assembler._get_user_about_me", return_value=""):
        result = await assemble(
            user_id="user-1", persona_id="p-1", model_unique_id="ollama_cloud:llama3.2",
        )

    assert result == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_prompt_assembler.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Create `backend/modules/chat/_prompt_assembler.py`:

```python
from backend.modules.chat._prompt_sanitiser import sanitise


async def _get_admin_prompt() -> str | None:
    """Fetch the global system prompt from settings."""
    from backend.modules.settings import get_setting
    return await get_setting("system_prompt")


async def _get_model_instructions(user_id: str, model_unique_id: str) -> str | None:
    """Fetch the user's per-model system prompt addition."""
    from backend.modules.llm import UserModelConfigRepository
    from backend.database import get_db
    repo = UserModelConfigRepository(get_db())
    config = await repo.find(user_id, model_unique_id)
    if config is None:
        return None
    return config.get("system_prompt_addition")


async def _get_persona_prompt(persona_id: str | None, user_id: str) -> str | None:
    """Fetch the persona's system prompt."""
    if not persona_id:
        return None
    from backend.modules.persona import get_persona
    persona = await get_persona(persona_id, user_id)
    if persona is None:
        return None
    return persona.get("system_prompt")


async def _get_user_about_me(user_id: str) -> str | None:
    """Fetch the user's about_me text."""
    from backend.modules.user import get_user_about_me
    return await get_user_about_me(user_id)


async def assemble(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
) -> str:
    """Assemble the full 4-layer XML system prompt for LLM consumption."""
    admin_prompt = await _get_admin_prompt()
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    # Layer 1: Admin — trusted, NOT sanitised
    if admin_prompt and admin_prompt.strip():
        parts.append(
            f'<systeminstructions priority="highest">\n{admin_prompt.strip()}\n</systeminstructions>'
        )

    # Layer 2: Model instructions — user-controlled, sanitised
    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(
                f'<modelinstructions priority="high">\n{cleaned}\n</modelinstructions>'
            )

    # Layer 3: Persona — user-controlled, sanitised
    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f'<you priority="normal">\n{cleaned}\n</you>')

    # Layer 4: User about_me — user-controlled, sanitised
    if user_about_me and user_about_me.strip():
        cleaned = sanitise(user_about_me.strip())
        if cleaned:
            parts.append(
                f'<userinfo priority="low">\nWhat the user wants you to know about themselves:\n{cleaned}\n</userinfo>'
            )

    return "\n\n".join(parts)


async def assemble_preview(
    user_id: str,
    persona_id: str | None,
    model_unique_id: str,
) -> str:
    """Assemble a human-readable preview (excludes admin prompt)."""
    model_instructions = await _get_model_instructions(user_id, model_unique_id)
    persona_prompt = await _get_persona_prompt(persona_id, user_id)
    user_about_me = await _get_user_about_me(user_id)

    parts: list[str] = []

    if model_instructions and model_instructions.strip():
        cleaned = sanitise(model_instructions.strip())
        if cleaned:
            parts.append(f"--- Model Instructions ---\n{cleaned}")

    if persona_prompt and persona_prompt.strip():
        cleaned = sanitise(persona_prompt.strip())
        if cleaned:
            parts.append(f"--- Persona ---\n{cleaned}")

    if user_about_me and user_about_me.strip():
        cleaned = sanitise(user_about_me.strip())
        if cleaned:
            parts.append(f"--- About Me ---\n{cleaned}")

    return "\n\n".join(parts)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_prompt_assembler.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_prompt_assembler.py tests/test_prompt_assembler.py
git commit -m "Add 4-layer XML system prompt assembler with sanitisation"
```

---

## Task 8: Context Window Manager

**Files:**
- Create: `backend/modules/chat/_context.py`
- Create: `tests/test_context_manager.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_context_manager.py`:

```python
import pytest
from backend.modules.chat._context import (
    calculate_budget,
    select_message_pairs,
    get_ampel_status,
    ContextBudget,
)


def test_calculate_budget():
    budget = calculate_budget(
        max_context_tokens=8192,
        system_prompt_tokens=200,
        new_message_tokens=50,
    )
    # safety = floor(8192 * 0.165) = 1351
    # response_reserve = 1000 + 50 = 1050
    # available = 8192 - 1351 - 200 - 1050 = 5591
    assert budget.available_for_chat == 5591
    assert budget.safety_reserve == 1351
    assert budget.response_reserve == 1050


def test_calculate_budget_negative_available_clamped_to_zero():
    budget = calculate_budget(
        max_context_tokens=2000,
        system_prompt_tokens=1500,
        new_message_tokens=500,
    )
    # safety = floor(2000 * 0.165) = 330
    # response_reserve = 1000 + 500 = 1500
    # available = 2000 - 330 - 1500 - 1500 = negative => 0
    assert budget.available_for_chat == 0


def test_select_message_pairs_all_fit():
    messages = [
        {"role": "user", "content": "hi", "token_count": 10},
        {"role": "assistant", "content": "hello", "token_count": 15},
        {"role": "user", "content": "bye", "token_count": 10},
        {"role": "assistant", "content": "cya", "token_count": 10},
    ]
    selected, total_tokens = select_message_pairs(messages, available_tokens=1000)
    assert len(selected) == 4
    assert total_tokens == 45


def test_select_message_pairs_budget_exceeded():
    messages = [
        {"role": "user", "content": "old", "token_count": 100},
        {"role": "assistant", "content": "old reply", "token_count": 100},
        {"role": "user", "content": "new", "token_count": 50},
        {"role": "assistant", "content": "new reply", "token_count": 50},
    ]
    # Budget only fits the newest pair
    selected, total_tokens = select_message_pairs(messages, available_tokens=150)
    assert len(selected) == 2
    assert selected[0]["content"] == "new"
    assert selected[1]["content"] == "new reply"
    assert total_tokens == 100


def test_select_message_pairs_empty():
    selected, total_tokens = select_message_pairs([], available_tokens=1000)
    assert selected == []
    assert total_tokens == 0


def test_select_message_pairs_single_user_message_no_pair():
    messages = [
        {"role": "user", "content": "hi", "token_count": 10},
    ]
    # Incomplete trailing pair — no complete pairs to select
    selected, total_tokens = select_message_pairs(messages, available_tokens=1000)
    assert selected == []
    assert total_tokens == 0


def test_get_ampel_green():
    assert get_ampel_status(0.3) == "green"
    assert get_ampel_status(0.0) == "green"
    assert get_ampel_status(0.49) == "green"


def test_get_ampel_yellow():
    assert get_ampel_status(0.5) == "yellow"
    assert get_ampel_status(0.64) == "yellow"


def test_get_ampel_orange():
    assert get_ampel_status(0.65) == "orange"
    assert get_ampel_status(0.79) == "orange"


def test_get_ampel_red():
    assert get_ampel_status(0.8) == "red"
    assert get_ampel_status(0.95) == "red"
    assert get_ampel_status(1.0) == "red"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_context_manager.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write minimal implementation**

Create `backend/modules/chat/_context.py`:

```python
import math
from dataclasses import dataclass
from typing import Literal


@dataclass
class ContextBudget:
    max_context_tokens: int
    system_prompt_tokens: int
    safety_reserve: int
    response_reserve: int
    available_for_chat: int


def calculate_budget(
    max_context_tokens: int,
    system_prompt_tokens: int,
    new_message_tokens: int,
) -> ContextBudget:
    """Calculate the token budget for chat message selection."""
    safety_reserve = math.floor(max_context_tokens * 0.165)
    response_reserve = 1000 + new_message_tokens
    available = max_context_tokens - safety_reserve - system_prompt_tokens - response_reserve
    return ContextBudget(
        max_context_tokens=max_context_tokens,
        system_prompt_tokens=system_prompt_tokens,
        safety_reserve=safety_reserve,
        response_reserve=response_reserve,
        available_for_chat=max(0, available),
    )


def select_message_pairs(
    messages: list[dict],
    available_tokens: int,
) -> tuple[list[dict], int]:
    """Select message pairs from newest to oldest within budget.

    Messages are grouped into (user, assistant) pairs.
    Returns (selected_messages_in_chronological_order, total_tokens).
    """
    # Group into pairs
    pairs: list[tuple[dict, dict]] = []
    i = 0
    while i + 1 < len(messages):
        if messages[i]["role"] == "user" and messages[i + 1]["role"] == "assistant":
            pairs.append((messages[i], messages[i + 1]))
            i += 2
        else:
            i += 1

    # Select from newest to oldest
    selected_pairs: list[tuple[dict, dict]] = []
    total_tokens = 0

    for pair in reversed(pairs):
        pair_tokens = pair[0]["token_count"] + pair[1]["token_count"]
        if total_tokens + pair_tokens > available_tokens:
            break
        selected_pairs.append(pair)
        total_tokens += pair_tokens

    # Reverse back to chronological order
    selected_pairs.reverse()

    result: list[dict] = []
    for user_msg, assistant_msg in selected_pairs:
        result.append(user_msg)
        result.append(assistant_msg)

    return result, total_tokens


def get_ampel_status(fill_ratio: float) -> Literal["green", "yellow", "orange", "red"]:
    """Return the context ampel status based on fill ratio (0.0 to 1.0)."""
    if fill_ratio >= 0.8:
        return "red"
    if fill_ratio >= 0.65:
        return "orange"
    if fill_ratio >= 0.5:
        return "yellow"
    return "green"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_context_manager.py -v`
Expected: all tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_context.py tests/test_context_manager.py
git commit -m "Add context window manager with budget calculation and ampel"
```

---

## Task 9: Shared Events and Topics for Edit/Regenerate

**Files:**
- Modify: `shared/topics.py`
- Modify: `shared/events/chat.py`
- Modify: `backend/ws/event_bus.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat_events_phase2.py`:

```python
from shared.events.chat import (
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatMessageDeletedEvent,
    ChatStreamEndedEvent,
)
from shared.topics import Topics
from datetime import datetime, timezone


def test_messages_truncated_event():
    now = datetime.now(timezone.utc)
    event = ChatMessagesTruncatedEvent(
        session_id="sess-1",
        after_message_id="msg-5",
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.messages.truncated"
    assert event.session_id == "sess-1"
    assert event.after_message_id == "msg-5"


def test_message_updated_event():
    now = datetime.now(timezone.utc)
    event = ChatMessageUpdatedEvent(
        session_id="sess-1",
        message_id="msg-5",
        content="edited content",
        token_count=42,
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.message.updated"


def test_message_deleted_event():
    now = datetime.now(timezone.utc)
    event = ChatMessageDeletedEvent(
        session_id="sess-1",
        message_id="msg-10",
        correlation_id="corr-1",
        timestamp=now,
    )
    assert event.type == "chat.message.deleted"


def test_stream_ended_has_fill_percentage():
    now = datetime.now(timezone.utc)
    event = ChatStreamEndedEvent(
        correlation_id="corr-1",
        session_id="sess-1",
        status="completed",
        usage=None,
        context_status="yellow",
        context_fill_percentage=0.55,
        timestamp=now,
    )
    assert event.context_fill_percentage == 0.55


def test_topics_exist():
    assert Topics.CHAT_MESSAGES_TRUNCATED == "chat.messages.truncated"
    assert Topics.CHAT_MESSAGE_UPDATED == "chat.message.updated"
    assert Topics.CHAT_MESSAGE_DELETED == "chat.message.deleted"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_chat_events_phase2.py -v`
Expected: FAIL — missing classes/attributes

- [ ] **Step 3: Add new Topics constants**

Add to the end of `shared/topics.py`:

```python
    # Chat edit/regenerate
    CHAT_MESSAGES_TRUNCATED = "chat.messages.truncated"
    CHAT_MESSAGE_UPDATED = "chat.message.updated"
    CHAT_MESSAGE_DELETED = "chat.message.deleted"
```

- [ ] **Step 4: Add new event models and update ChatStreamEndedEvent**

Add to `shared/events/chat.py` (at the end of the file):

```python
class ChatMessagesTruncatedEvent(BaseModel):
    type: str = "chat.messages.truncated"
    session_id: str
    after_message_id: str
    correlation_id: str
    timestamp: datetime


class ChatMessageUpdatedEvent(BaseModel):
    type: str = "chat.message.updated"
    session_id: str
    message_id: str
    content: str
    token_count: int
    correlation_id: str
    timestamp: datetime


class ChatMessageDeletedEvent(BaseModel):
    type: str = "chat.message.deleted"
    session_id: str
    message_id: str
    correlation_id: str
    timestamp: datetime
```

Also add `context_fill_percentage` field to `ChatStreamEndedEvent`:

```python
class ChatStreamEndedEvent(BaseModel):
    type: str = "chat.stream.ended"
    correlation_id: str
    session_id: str
    status: Literal["completed", "cancelled", "error"]
    usage: dict | None = None
    context_status: Literal["green", "yellow", "orange", "red"]
    context_fill_percentage: float = 0.0
    timestamp: datetime
```

- [ ] **Step 5: Add fan-out rules**

Add to `backend/ws/event_bus.py` in the `_FANOUT` dict:

```python
    Topics.CHAT_MESSAGES_TRUNCATED: ([], True),
    Topics.CHAT_MESSAGE_UPDATED: ([], True),
    Topics.CHAT_MESSAGE_DELETED: ([], True),
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_chat_events_phase2.py -v`
Expected: all 5 tests PASS

- [ ] **Step 7: Run existing tests to check nothing is broken**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_shared_chat_contracts.py tests/test_inference_runner.py -v`
Expected: all existing tests still PASS (ChatStreamEndedEvent has a default for `context_fill_percentage`)

- [ ] **Step 8: Commit**

```bash
git add shared/topics.py shared/events/chat.py backend/ws/event_bus.py tests/test_chat_events_phase2.py
git commit -m "Add shared events and topics for message edit and regenerate"
```

---

## Task 10: Chat Repository — New Query Methods

**Files:**
- Modify: `backend/modules/chat/_repository.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_chat_repo_phase2.py`:

```python
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock


@pytest.fixture
def mock_db():
    db = MagicMock()
    db["chat_sessions"] = AsyncMock()
    db["chat_messages"] = AsyncMock()
    return db


def _make_message(msg_id: str, session_id: str, role: str, content: str, minutes_ago: int = 0):
    return {
        "_id": msg_id,
        "session_id": session_id,
        "role": role,
        "content": content,
        "token_count": len(content),
        "created_at": datetime.now(timezone.utc) - timedelta(minutes=minutes_ago),
    }


async def test_delete_messages_after(mock_db):
    from backend.modules.chat._repository import ChatRepository

    target_msg = _make_message("msg-3", "sess-1", "user", "target", minutes_ago=5)
    mock_db["chat_messages"].find_one = AsyncMock(return_value=target_msg)
    mock_db["chat_messages"].delete_many = AsyncMock()

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_after("sess-1", "msg-3")

    assert result is True
    mock_db["chat_messages"].delete_many.assert_awaited_once()
    call_filter = mock_db["chat_messages"].delete_many.call_args[0][0]
    assert call_filter["session_id"] == "sess-1"
    assert "$gt" in str(call_filter["created_at"])


async def test_delete_messages_after_not_found(mock_db):
    from backend.modules.chat._repository import ChatRepository

    mock_db["chat_messages"].find_one = AsyncMock(return_value=None)

    repo = ChatRepository(mock_db)
    result = await repo.delete_messages_after("sess-1", "nonexistent")
    assert result is False


async def test_update_message_content(mock_db):
    from backend.modules.chat._repository import ChatRepository

    updated_doc = _make_message("msg-3", "sess-1", "user", "edited content")
    mock_db["chat_messages"].update_one = AsyncMock()
    mock_db["chat_messages"].find_one = AsyncMock(return_value=updated_doc)

    repo = ChatRepository(mock_db)
    result = await repo.update_message_content("msg-3", "edited content", 15)

    assert result is not None
    assert result["content"] == "edited content"
    mock_db["chat_messages"].update_one.assert_awaited_once()


async def test_get_last_message(mock_db):
    from backend.modules.chat._repository import ChatRepository

    last_msg = _make_message("msg-10", "sess-1", "assistant", "last reply")

    cursor_mock = MagicMock()
    cursor_mock.sort = MagicMock(return_value=cursor_mock)
    cursor_mock.limit = MagicMock(return_value=cursor_mock)
    cursor_mock.to_list = AsyncMock(return_value=[last_msg])
    mock_db["chat_messages"].find = MagicMock(return_value=cursor_mock)

    repo = ChatRepository(mock_db)
    result = await repo.get_last_message("sess-1")

    assert result is not None
    assert result["_id"] == "msg-10"


async def test_get_last_message_empty_session(mock_db):
    from backend.modules.chat._repository import ChatRepository

    cursor_mock = MagicMock()
    cursor_mock.sort = MagicMock(return_value=cursor_mock)
    cursor_mock.limit = MagicMock(return_value=cursor_mock)
    cursor_mock.to_list = AsyncMock(return_value=[])
    mock_db["chat_messages"].find = MagicMock(return_value=cursor_mock)

    repo = ChatRepository(mock_db)
    result = await repo.get_last_message("sess-1")
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_chat_repo_phase2.py -v`
Expected: FAIL — methods don't exist

- [ ] **Step 3: Add new methods to ChatRepository**

Add to `backend/modules/chat/_repository.py` (inside the `ChatRepository` class, after `list_messages`):

```python
    async def delete_messages_after(self, session_id: str, message_id: str) -> bool:
        """Delete all messages in a session created after the given message."""
        target = await self._messages.find_one({"_id": message_id, "session_id": session_id})
        if target is None:
            return False
        await self._messages.delete_many({
            "session_id": session_id,
            "created_at": {"$gt": target["created_at"]},
        })
        return True

    async def update_message_content(
        self, message_id: str, content: str, token_count: int,
    ) -> dict | None:
        """Overwrite a message's content and token count."""
        await self._messages.update_one(
            {"_id": message_id},
            {"$set": {"content": content, "token_count": token_count}},
        )
        return await self._messages.find_one({"_id": message_id})

    async def get_last_message(self, session_id: str) -> dict | None:
        """Return the last message in a session by created_at, or None."""
        cursor = self._messages.find({"session_id": session_id}).sort("created_at", -1).limit(1)
        docs = await cursor.to_list(length=1)
        return docs[0] if docs else None

    async def delete_message(self, message_id: str) -> bool:
        """Delete a single message by ID."""
        result = await self._messages.delete_one({"_id": message_id})
        return result.deleted_count > 0
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_chat_repo_phase2.py -v`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add backend/modules/chat/_repository.py tests/test_chat_repo_phase2.py
git commit -m "Add repository methods for message truncation, update, and deletion"
```

---

## Task 11: Refactor `handle_chat_send` — Extract `_run_inference`

**Files:**
- Modify: `backend/modules/chat/__init__.py`
- Modify: `backend/modules/chat/_inference.py`

This is the core refactor. The existing `handle_chat_send` is split: message preparation stays in the handler, and the inference orchestration (prompt assembly, context selection, InferenceRunner invocation) moves into `_run_inference`.

- [ ] **Step 1: Update InferenceRunner to accept context params**

Modify `backend/modules/chat/_inference.py` — the `ChatStreamEndedEvent` emission needs `context_fill_percentage`. Change the `_run_locked` method to accept and pass through these params:

Replace the full `_run_locked` method signature and `ChatStreamEndedEvent` emission:

```python
    async def _run_locked(
        self,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
    ) -> None:
```

And update the `run` method to accept and forward these:

```python
    async def run(
        self,
        user_id: str,
        session_id: str,
        correlation_id: str,
        stream_fn: Callable,
        emit_fn: Callable,
        save_fn: Callable,
        cancel_event: asyncio.Event | None = None,
        context_status: str = "green",
        context_fill_percentage: float = 0.0,
    ) -> None:
        lock = self._get_lock(user_id)
        async with lock:
            await self._run_locked(
                session_id, correlation_id, stream_fn, emit_fn, save_fn, cancel_event,
                context_status, context_fill_percentage,
            )
```

And update the `ChatStreamEndedEvent` at the end of `_run_locked`:

```python
        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status=status,
            usage=usage,
            context_status=context_status,
            context_fill_percentage=context_fill_percentage,
            timestamp=datetime.now(timezone.utc),
        ))
```

- [ ] **Step 2: Refactor `handle_chat_send` and extract `_run_inference`**

Replace the entire contents of `backend/modules/chat/__init__.py` with:

```python
"""Chat module — sessions, messages, inference orchestration.

Public API: import only from this file.
"""

import asyncio
import logging
from datetime import datetime, timezone
from uuid import uuid4

from backend.modules.chat._handlers import router
from backend.modules.chat._inference import InferenceRunner
from backend.modules.chat._repository import ChatRepository
from backend.modules.chat._token_counter import count_tokens
from backend.modules.chat._prompt_assembler import assemble
from backend.modules.chat._context import calculate_budget, select_message_pairs, get_ampel_status
from backend.database import get_db
from backend.modules.llm import (
    stream_completion as llm_stream_completion,
    get_model_context_window,
    LlmCredentialNotFoundError,
)
from backend.modules.persona import get_persona
from backend.ws.event_bus import get_event_bus
from backend.ws.manager import get_manager
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart
from shared.events.chat import (
    ChatContentDeltaEvent,
    ChatMessageDeletedEvent,
    ChatMessagesTruncatedEvent,
    ChatMessageUpdatedEvent,
    ChatStreamEndedEvent,
    ChatStreamErrorEvent,
    ChatStreamStartedEvent,
    ChatThinkingDeltaEvent,
)
from shared.topics import Topics

_log = logging.getLogger(__name__)

_runner = InferenceRunner()

# Active cancel events keyed by correlation_id
_cancel_events: dict[str, asyncio.Event] = {}

_DEFAULT_CONTEXT_WINDOW = 8192


async def init_indexes(db) -> None:
    """Create MongoDB indexes for the chat module collections."""
    await ChatRepository(db).create_indexes()


async def _run_inference(
    user_id: str,
    session_id: str,
    repo: ChatRepository,
    session: dict,
) -> None:
    """Shared inference path used by send, edit, and regenerate."""
    persona_id = session.get("persona_id")
    model_unique_id = session.get("model_unique_id", "")

    if ":" not in model_unique_id:
        _log.error("Invalid model_unique_id format: %s", model_unique_id)
        await repo.update_session_state(session_id, "idle")
        return

    provider_id, model_slug = model_unique_id.split(":", 1)

    # Assemble system prompt
    system_prompt = await assemble(
        user_id=user_id,
        persona_id=persona_id,
        model_unique_id=model_unique_id,
    )
    system_prompt_tokens = count_tokens(system_prompt) if system_prompt else 0

    # Get context window size
    max_context = await get_model_context_window(provider_id, model_slug)
    if max_context is None or max_context == 0:
        max_context = _DEFAULT_CONTEXT_WINDOW

    # Load message history
    history_docs = await repo.list_messages(session_id)

    # The last message should be the user's new message
    new_msg_tokens = history_docs[-1]["token_count"] if history_docs else 0

    # Calculate budget (exclude the new user message from pair selection)
    budget = calculate_budget(
        max_context_tokens=max_context,
        system_prompt_tokens=system_prompt_tokens,
        new_message_tokens=new_msg_tokens,
    )

    # Check if context is full (pre-send check)
    all_history_tokens = sum(doc["token_count"] for doc in history_docs)
    total_tokens_used = system_prompt_tokens + all_history_tokens
    fill_ratio = total_tokens_used / max_context if max_context > 0 else 1.0

    if fill_ratio >= 0.8:
        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        manager = get_manager()
        await manager.send_to_user(user_id, ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="context_window_full",
            recoverable=False,
            user_message="Context window is full. Please start a new session.",
            timestamp=now,
        ).model_dump(mode="json"))
        await repo.update_session_state(session_id, "idle")
        return

    # Pair-based backread: select history pairs (exclude last user message)
    history_for_pairs = history_docs[:-1] if history_docs else []
    selected_history, _ = select_message_pairs(history_for_pairs, budget.available_for_chat)

    # Build messages for the LLM
    messages: list[CompletionMessage] = []

    if system_prompt:
        messages.append(CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=system_prompt)],
        ))

    for doc in selected_history:
        messages.append(CompletionMessage(
            role=doc["role"],
            content=[ContentPart(type="text", text=doc["content"])],
        ))

    # Append the new user message
    if history_docs:
        last_msg = history_docs[-1]
        messages.append(CompletionMessage(
            role=last_msg["role"],
            content=[ContentPart(type="text", text=last_msg["content"])],
        ))

    # Get persona settings for temperature/reasoning
    persona = await get_persona(persona_id, user_id) if persona_id else None

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=persona.get("temperature") if persona else None,
        reasoning_enabled=persona.get("reasoning_enabled", False) if persona else False,
    )

    # Set session state to streaming
    await repo.update_session_state(session_id, "streaming")

    correlation_id = str(uuid4())
    cancel_event = asyncio.Event()
    _cancel_events[correlation_id] = cancel_event

    manager = get_manager()
    event_bus = get_event_bus()

    _DELTA_TYPES = {Topics.CHAT_CONTENT_DELTA, Topics.CHAT_THINKING_DELTA}

    async def emit_fn(event) -> None:
        event_dict = event.model_dump(mode="json")
        event_type = event_dict.get("type", "")

        if event_type in _DELTA_TYPES:
            await manager.send_to_user(user_id, event_dict)
        else:
            await event_bus.publish(
                event_type,
                event,
                scope=f"session:{session_id}",
                target_user_ids=[user_id],
                correlation_id=correlation_id,
            )

    def stream_fn():
        return llm_stream_completion(user_id, provider_id, request)

    async def save_fn(content: str, thinking: str | None, usage: dict | None) -> None:
        token_count = count_tokens(content)
        await repo.save_message(
            session_id,
            role="assistant",
            content=content,
            token_count=token_count,
            thinking=thinking,
        )
        await repo.update_session_state(session_id, "idle")

    # Calculate ampel status for the response
    context_status = get_ampel_status(fill_ratio)

    try:
        await _runner.run(
            user_id=user_id,
            session_id=session_id,
            correlation_id=correlation_id,
            stream_fn=stream_fn,
            emit_fn=emit_fn,
            save_fn=save_fn,
            cancel_event=cancel_event,
            context_status=context_status,
            context_fill_percentage=fill_ratio,
        )
    except LlmCredentialNotFoundError:
        now = datetime.now(timezone.utc)
        await emit_fn(ChatStreamStartedEvent(
            session_id=session_id, correlation_id=correlation_id, timestamp=now,
        ))
        await emit_fn(ChatStreamErrorEvent(
            correlation_id=correlation_id,
            error_code="credential_not_found",
            recoverable=False,
            user_message="No API key configured for this model's provider. Please add one in settings.",
            timestamp=now,
        ))
        await emit_fn(ChatStreamEndedEvent(
            correlation_id=correlation_id,
            session_id=session_id,
            status="error",
            usage=None,
            context_status="green",
            context_fill_percentage=0.0,
            timestamp=now,
        ))
        await repo.update_session_state(session_id, "idle")
    except Exception as e:
        _log.error("Unexpected error in _run_inference for session %s: %s", session_id, e)
        await repo.update_session_state(session_id, "idle")
    finally:
        _cancel_events.pop(correlation_id, None)


async def handle_chat_send(user_id: str, data: dict) -> None:
    """Handle a chat.send WebSocket message — save user message, run inference."""
    session_id = data.get("session_id")
    content_parts = data.get("content")
    if not session_id or not content_parts:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session:
            return

        if session.get("state") != "idle":
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            return

        token_count = count_tokens(text)
        await repo.save_message(session_id, role="user", content=text, token_count=token_count)

        await _run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_send for user %s", user_id)


async def handle_chat_edit(user_id: str, data: dict) -> None:
    """Handle a chat.edit WebSocket message — truncate, update, re-infer."""
    session_id = data.get("session_id")
    message_id = data.get("message_id")
    content_parts = data.get("content")
    if not session_id or not message_id or not content_parts:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session or session.get("state") != "idle":
            return

        # Validate message exists and belongs to this session
        messages = await repo.list_messages(session_id)
        target = None
        for msg in messages:
            if msg["_id"] == message_id:
                target = msg
                break

        if target is None or target["role"] != "user":
            return

        text = "".join(
            part.get("text", "") for part in content_parts if part.get("type") == "text"
        ).strip()
        if not text:
            return

        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        # Truncate messages after the target
        await repo.delete_messages_after(session_id, message_id)

        await event_bus.publish(
            Topics.CHAT_MESSAGES_TRUNCATED,
            ChatMessagesTruncatedEvent(
                session_id=session_id,
                after_message_id=message_id,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        # Update the target message
        token_count = count_tokens(text)
        await repo.update_message_content(message_id, text, token_count)

        await event_bus.publish(
            Topics.CHAT_MESSAGE_UPDATED,
            ChatMessageUpdatedEvent(
                session_id=session_id,
                message_id=message_id,
                content=text,
                token_count=token_count,
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        # Run inference
        await _run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_edit for user %s", user_id)


async def handle_chat_regenerate(user_id: str, data: dict) -> None:
    """Handle a chat.regenerate WebSocket message — delete last assistant msg, re-infer."""
    session_id = data.get("session_id")
    if not session_id:
        return

    try:
        db = get_db()
        repo = ChatRepository(db)

        session = await repo.get_session(session_id, user_id)
        if not session or session.get("state") != "idle":
            return

        last_msg = await repo.get_last_message(session_id)
        if last_msg is None or last_msg["role"] != "assistant":
            return

        correlation_id = str(uuid4())
        now = datetime.now(timezone.utc)
        event_bus = get_event_bus()

        # Delete the last assistant message
        await repo.delete_message(last_msg["_id"])

        await event_bus.publish(
            Topics.CHAT_MESSAGE_DELETED,
            ChatMessageDeletedEvent(
                session_id=session_id,
                message_id=last_msg["_id"],
                correlation_id=correlation_id,
                timestamp=now,
            ),
            scope=f"session:{session_id}",
            target_user_ids=[user_id],
            correlation_id=correlation_id,
        )

        # Run inference using existing last user message
        await _run_inference(user_id, session_id, repo, session)
    except Exception:
        _log.exception("Unhandled error in handle_chat_regenerate for user %s", user_id)


def handle_chat_cancel(user_id: str, data: dict) -> None:
    """Handle a chat.cancel WebSocket message — signal cancellation."""
    correlation_id = data.get("correlation_id")
    if correlation_id and correlation_id in _cancel_events:
        _cancel_events[correlation_id].set()


__all__ = [
    "router", "init_indexes",
    "handle_chat_send", "handle_chat_edit", "handle_chat_regenerate",
    "handle_chat_cancel",
]
```

- [ ] **Step 3: Run existing inference runner tests**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/test_inference_runner.py -v`
Expected: all tests still PASS

- [ ] **Step 4: Commit**

```bash
git add backend/modules/chat/__init__.py backend/modules/chat/_inference.py
git commit -m "Refactor chat module: extract _run_inference, add edit and regenerate handlers"
```

---

## Task 12: WebSocket Router — Add Edit and Regenerate Dispatch

**Files:**
- Modify: `backend/ws/router.py`

- [ ] **Step 1: Add dispatch for new message types**

Modify `backend/ws/router.py`:

Update the import:

```python
from backend.modules.chat import handle_chat_send, handle_chat_cancel, handle_chat_edit, handle_chat_regenerate
```

Add in the `while True` loop, after the `chat.cancel` handler:

```python
            elif msg_type == "chat.edit":
                task = asyncio.create_task(handle_chat_edit(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
            elif msg_type == "chat.regenerate":
                task = asyncio.create_task(handle_chat_regenerate(user_id, data))
                _background_tasks.add(task)
                task.add_done_callback(_background_tasks.discard)
```

- [ ] **Step 2: Run existing router tests**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/ws/test_router.py -v`
Expected: existing tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/ws/router.py
git commit -m "Add chat.edit and chat.regenerate dispatch to WebSocket router"
```

---

## Task 13: Update `INFERENCE-IMPLEMENTATION-STATE.md`

**Files:**
- Modify: `INFERENCE-IMPLEMENTATION-STATE.md`

- [ ] **Step 1: Update the state document**

Replace the Phase 2 section status from "TO DO" to "COMPLETE" and update the known limitations:

Mark Phase 2 as complete. Update the "Known limitations" section in Phase 1 to strike through the resolved items. Add a Phase 2 "What was built" table with all new files and modifications.

- [ ] **Step 2: Commit**

```bash
git add INFERENCE-IMPLEMENTATION-STATE.md
git commit -m "Update inference implementation state: Phase 2 complete"
```

---

## Task 14: Full Test Suite Run

- [ ] **Step 1: Run all tests**

Run: `cd /home/chris/workspace/chatsune && uv run --directory backend pytest tests/ -v --tb=short`
Expected: all tests PASS, no regressions

- [ ] **Step 2: Fix any failures if needed**

If tests fail, diagnose and fix. Re-run until green.

- [ ] **Step 3: Final commit if any fixes were needed**

Only if fixes were applied in Step 2.
