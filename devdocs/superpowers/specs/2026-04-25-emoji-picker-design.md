# Emoji Picker — Design

**Status:** approved (brainstorming)
**Date:** 2026-04-25
**Owner:** Chris (navigator4223@gmail.com)

## Problem

Chatsune lacks an emoji picker in the chat input. Users currently cannot insert
emojis without an OS-level picker (alt-shortcuts, system tray, keyboard
overlays), which is awkward on mobile and inconsistent across browsers. We want
a built-in picker that works on desktop and mobile, has search, and remembers
each user's six most recently used emojis.

A reaction-style emoji response on other users' messages is **not** in scope.
For Chatsune, an emoji typed in the message body is semantically equivalent to
a reaction, and a separate reaction layer adds product complexity for no user
benefit.

## Goals

- Picker available on desktop (anchored popover inside the chat input field)
  and mobile (inline panel above the cockpit bar).
- Real search (text → emoji match), Skin-tone switcher, dark theme matching
  the app surface.
- Per-user "Recent" row at the top of the picker — exactly six emojis,
  most-recent-first, persisted server-side, synchronised across tabs and
  devices via WebSocket.
- LRU updates **on send**, not on click, so discarded drafts and rapid
  insertion experiments do not pollute the list.
- Default Recent set for first-time users:
  `👍 ❤️ 😂 🤘 😊 🔥` (the fourth slot is "metal" rather than "celebrate" as
  Chatsune branding).

## Non-Goals

- Reactions on existing messages (Phase II — not pursued; see Problem section).
- Custom / uploaded emoji.
- Per-conversation emoji sets, animated emoji, or emoji-bundle marketplaces.
- Migrating server-side LRU to a separate collection — six strings per user
  fits comfortably on the `users` document.

## Library Choice

**`@emoji-mart/react`** with native (system font) rendering, lazy-loaded on
first picker open.

- Mature, mobile-tested, dark-theme-capable, search built in, skin-tone
  switcher included.
- ~600 KB combined picker + emoji data — never on the critical render path
  thanks to `React.lazy` + dynamic `import('@emoji-mart/data')`.
- The library's own "Frequently Used" section is suppressed; we render our
  own `LRUBar` above the picker so the list is server-driven, not
  LocalStorage-driven.

Alternatives considered:
- `emoji-picker-react` — lighter, but its "Recent" is hard-mapped to
  LocalStorage; replacing it requires hiding the built-in row and overlaying
  ours. Same effective architecture, smaller library.
- `frimousse` — too much DIY for a 36-hour delivery; we would build the
  search index, mobile sheet, and skin-tone selector ourselves.

## Architecture Overview

```
Frontend (React/TSX)
  ChatInput.tsx
    ├── Smile-Trigger (desktop: inside textarea / mobile: cockpit slot)
    ├── EmojiPickerPopover (lazy, @emoji-mart/react)
    │     └── LRUBar — six-button row above the picker body
    └── insertEmojiAtCursor()
  emojiPickerStore (zustand)  — open/close/toggle
  recentEmojisStore (zustand) — fed by initial fetch + WS event

Backend (FastAPI / Python)
  modules/user/
    UserDocument.recent_emojis: list[str]
    UserService.touch_recent_emojis(user_id, emojis_in_text)
      → repository.update_recent_emojis()
      → publish USER_RECENT_EMOJIS_UPDATED
  modules/chat/_handlers.py
    on send: extract_emojis(text) → user_service.touch_recent_emojis(...)
  shared/
    topics.py: USER_RECENT_EMOJIS_UPDATED
    events/auth.py: RecentEmojisUpdatedEvent
    dtos/auth.py: UserDto.recent_emojis
```

### Send Flow

1. User types `Hallo 👋 😊` and triggers send.
2. Frontend dispatches the message via the existing chat WebSocket pipeline.
3. Backend chat handler persists the message, then calls
   `user_service.touch_recent_emojis(user_id, ['👋', '😊'])`. The call is
   wrapped in `try/except` — the LRU is comfort, not a critical path.
4. UserService dedupes and caps at six, writes the user document, publishes
   `USER_RECENT_EMOJIS_UPDATED` scoped to `user:{user_id}` so all of that
   user's open sessions receive it.
5. Each tab's `recentEmojisStore` updates; `LRUBar` re-renders with the new
   order.

### Module Boundaries

- The chat module **only** uses the public `UserService` API; no direct
  access to user repositories or models, in line with CLAUDE.md.
- The frontend imports event types and topic constants from `shared/`, never
  from a backend internal.

## Backend Specification

### `backend/modules/user/_models.py`

```python
DEFAULT_RECENT_EMOJIS = ["👍", "❤️", "😂", "🤘", "😊", "🔥"]

class UserDocument(BaseModel):
    # ... existing fields ...
    recent_emojis: list[str] = Field(default_factory=lambda: list(DEFAULT_RECENT_EMOJIS))
```

The `default_factory` covers two cases simultaneously: (a) a freshly created
user gets the branded set, and (b) an existing document without the field
loads cleanly with the same default. No migration script required — this
satisfies the post-2026-04-15 "no wipe" rule from CLAUDE.md.

### `backend/modules/user/_repository.py`

```python
async def update_recent_emojis(self, user_id: str, emojis: list[str]) -> None:
    await self.collection.update_one(
        {"_id": user_id},
        {"$set": {"recent_emojis": emojis, "updated_at": datetime.utcnow()}},
    )
```

### `backend/modules/user/__init__.py` — Public API

`UserService.touch_recent_emojis` is added to the existing public surface:

```python
async def touch_recent_emojis(self, user_id: str, emojis_in_text: list[str]) -> None:
    """Move freshly-used emojis to the front of the user's recent list.
    Idempotent — duplicates in `emojis_in_text` are tolerated; no-op when
    the list is empty or the resulting LRU is unchanged."""
    if not emojis_in_text:
        return
    user = await self._repository.get_by_id(user_id)
    if user is None:
        return
    new_list = self._merge_lru(user.recent_emojis, emojis_in_text, max_size=6)
    if new_list == user.recent_emojis:
        return
    await self._repository.update_recent_emojis(user_id, new_list)
    await self._event_bus.publish(
        Topics.USER_RECENT_EMOJIS_UPDATED,
        RecentEmojisUpdatedEvent(user_id=user_id, emojis=new_list),
        scope=f"user:{user_id}",
    )

@staticmethod
def _merge_lru(current: list[str], incoming: list[str], max_size: int) -> list[str]:
    """Front-load `incoming` (in order, deduped), then append remaining
    items from `current`. Cap at `max_size`."""
    seen: set[str] = set()
    merged: list[str] = []
    for emoji in [*incoming, *current]:
        if emoji in seen:
            continue
        seen.add(emoji)
        merged.append(emoji)
        if len(merged) >= max_size:
            break
    return merged
```

### `backend/modules/chat/_emoji_extractor.py`

```python
import regex  # `regex` package, not the stdlib `re`

_EMOJI_RE = regex.compile(
    r"\p{Extended_Pictographic}(?:\p{EMod}|\u200d\p{Extended_Pictographic})*"
)

def extract_emojis(text: str) -> list[str]:
    """Return emojis in order of appearance, preserving skin-tone modifiers
    and ZWJ-joined sequences as single units."""
    return _EMOJI_RE.findall(text)
```

`regex` (not `re`) is required — the standard library does not understand
`\p{Extended_Pictographic}`. The dependency must be added to **both**
`pyproject.toml` (root) and `backend/pyproject.toml` per CLAUDE.md.

### `backend/modules/chat/_handlers.py`

In the existing send-message handler, after the message has been persisted
and before the LLM is dispatched:

```python
try:
    emojis = extract_emojis(message_text)
    if emojis:
        await self._user_service.touch_recent_emojis(user_id, emojis)
except Exception as exc:
    logger.warning(
        "recent_emojis_update_failed",
        user_id=user_id,
        error=str(exc),
    )
```

The `try/except` is intentional: the LRU is comfort, not a critical path.
A Mongo blip must not block the chat send.

### Shared Contracts

`shared/topics.py`:

```python
USER_RECENT_EMOJIS_UPDATED = "user.recent_emojis.updated"
```

`shared/events/auth.py`:

```python
class RecentEmojisUpdatedEvent(BaseModel):
    type: Literal["user.recent_emojis.updated"] = "user.recent_emojis.updated"
    user_id: str
    emojis: list[str]
```

`shared/dtos/auth.py` — extend `UserDto`:

```python
class UserDto(BaseModel):
    # ... existing fields ...
    recent_emojis: list[str] = Field(default_factory=list)
```

The default keeps existing GET-user response consumers happy if a backend
predates this change (defensive only — production bumps both ends together).

### REST endpoint

No new endpoint. The existing "current user" endpoint (`GET /api/users/me`
or equivalent) returns `UserDto`, which now includes `recent_emojis`. The
frontend uses that for initial hydration; from then on, WebSocket events
keep the store fresh.

## Frontend Specification

### `frontend/src/features/chat/emojiPickerStore.ts`

```ts
import { create } from 'zustand'

export const useEmojiPickerStore = create<{
  isOpen: boolean
  open: () => void
  close: () => void
  toggle: () => void
}>((set) => ({
  isOpen: false,
  open: () => set({ isOpen: true }),
  close: () => set({ isOpen: false }),
  toggle: () => set((s) => ({ isOpen: !s.isOpen })),
}))
```

### `frontend/src/features/user/recentEmojisStore.ts`

```ts
import { create } from 'zustand'

export const useRecentEmojisStore = create<{
  emojis: string[]
  set: (emojis: string[]) => void
}>((set) => ({
  emojis: [],
  set: (emojis) => set({ emojis }),
}))
```

The store is hydrated on initial user fetch (existing flow) and updated
live by the WebSocket event router on `USER_RECENT_EMOJIS_UPDATED`.

### Trigger wiring

- **Cockpit-Button** (`CockpitBar.tsx`): `onClick={useEmojiPickerStore.getState().toggle}`.
  The button reflects open state with `state="active"`.
- **Textarea Smile-Button** (`ChatInput.tsx`): identical `onClick`.
- **Close triggers**: clicking either trigger again, the Escape key, an
  outside click handler on the picker container, and `onFocus` of the
  textarea (so tapping back into the input always closes the picker).

### `frontend/src/features/chat/EmojiPickerPopover.tsx`

```tsx
const Picker = lazy(() => import('@emoji-mart/react'))
const dataPromise = import('@emoji-mart/data')

interface Props {
  onSelect: (emoji: string) => void
  onClose: () => void
}

export function EmojiPickerPopover({ onSelect, onClose }: Props) {
  const { isMobile } = useViewport()
  const recent = useRecentEmojisStore((s) => s.emojis)
  const containerRef = useRef<HTMLDivElement>(null)

  useOutsideClick(containerRef, onClose)
  useEscapeKey(onClose)

  const containerClass = isMobile
    ? 'absolute bottom-full left-0 right-0 mb-2 z-40'
    : 'absolute bottom-full right-0 mb-2 z-40'

  return (
    <div ref={containerRef} className={containerClass}>
      <LRUBar emojis={recent} onSelect={onSelect} />
      <Suspense fallback={<PickerSkeleton />}>
        <Picker
          data={dataPromise}
          onEmojiSelect={(e: { native: string }) => onSelect(e.native)}
          theme="dark"
          set="native"
          previewPosition="none"
          skinTonePosition="search"
          categories={[
            'people', 'nature', 'foods', 'activity',
            'places', 'objects', 'symbols', 'flags',
          ]}
        />
      </Suspense>
    </div>
  )
}
```

- `set="native"` uses the system emoji font — no image atlas download.
- `previewPosition="none"` removes the preview row, important on mobile.
- `skinTonePosition="search"` tucks the skin-tone selector next to the
  search field, which is compact and matches modern picker UX.
- The library's `frequent` category is omitted — `LRUBar` provides ours.

### `frontend/src/features/chat/LRUBar.tsx`

```tsx
export function LRUBar({
  emojis,
  onSelect,
}: {
  emojis: string[]
  onSelect: (e: string) => void
}) {
  if (emojis.length === 0) return null
  return (
    <div className="flex items-center gap-1 rounded-t-lg border-b border-white/8 bg-[#1a1625] px-2 py-1.5">
      <span className="text-[10px] uppercase tracking-wider text-white/40 mr-2">
        Recent
      </span>
      {emojis.map((e) => (
        <button
          key={e}
          type="button"
          onClick={() => onSelect(e)}
          className="rounded-md px-1.5 py-0.5 text-lg transition-colors hover:bg-white/10"
        >
          {e}
        </button>
      ))}
    </div>
  )
}
```

### `frontend/src/features/chat/insertEmojiAtCursor.ts`

```ts
const EMOJI_RE = /\p{Extended_Pictographic}/u

export function insertEmojiAtCursor(
  textarea: HTMLTextAreaElement,
  emoji: string,
): { value: string; cursor: number } {
  const { value, selectionStart, selectionEnd } = textarea
  const before = value.slice(0, selectionStart)
  const after = value.slice(selectionEnd)

  const prevChar = before.slice(-1)
  const nextChar = after.slice(0, 1)

  const needsLead =
    prevChar !== '' && !/\s/.test(prevChar) && !EMOJI_RE.test(prevChar)
  const needsTrail =
    nextChar !== '' && !/\s/.test(nextChar) && !EMOJI_RE.test(nextChar)

  const insertion = (needsLead ? ' ' : '') + emoji + (needsTrail ? ' ' : '')
  const newValue = before + insertion + after
  const newCursor = before.length + insertion.length
  return { value: newValue, cursor: newCursor }
}
```

Insertion rules (Chris's spec):

- Add a leading space iff the previous character is non-empty, not
  whitespace, and not an emoji.
- Add a trailing space iff the next character is non-empty, not
  whitespace, and not an emoji.
- The cursor lands directly after the inserted emoji. Multiple emojis in
  a row produce no internal spaces.

### ChatInput integration

```ts
const handleEmojiSelect = (emoji: string) => {
  const ta = textareaRef.current
  if (!ta) return
  const { value, cursor } = insertEmojiAtCursor(ta, emoji)
  setText(value)
  requestAnimationFrame(() => {
    ta.focus()
    ta.setSelectionRange(cursor, cursor)
  })
  // Picker stays open — Discord/Slack pattern: users typically pick
  // several emojis in a row.
}
```

The picker remains open after a selection. Closing is explicit
(Escape, outside click, trigger toggle, textarea focus).

## Edge Cases

- **ZWJ sequences and skin-tone variants** are preserved as single units by
  the backend `regex` pattern and treated as opaque strings on the frontend.
- **Identical emojis in one message** (`"😂😂😂"`): `_merge_lru` dedupes; one
  occurrence floats to the front.
- **Corrupt LRU** (any document with more than six entries from a future
  bug): the repository read path slices to six. Pydantic validation does
  not enforce a max length so old documents continue to load.
- **Picker lazy-load fails** (network hiccup): `Suspense` keeps the skeleton
  visible. After ~5 s an `ErrorBoundary` surfaces a "Picker failed to load —
  Retry" message. The `LRUBar` remains usable in the meantime.
- **Disabled textarea** (during streaming): trigger buttons are disabled;
  picker stays closed. If already open when streaming starts, the picker
  remains visible but selection is a no-op (textarea is read-only).
- **WebSocket disconnect with picker open**: state is in-memory and survives
  reconnect; missed `USER_RECENT_EMOJIS_UPDATED` events are caught up via
  the existing Redis Streams replay.

## Testing

### Backend (pytest, **Docker-only** — see memory `feedback_db_tests_on_host`)

- `tests/backend/modules/chat/test_emoji_extractor.py`: ASCII-only text,
  ZWJ sequences (`👨‍👩‍👧‍👦`), skin-tones (`👍🏽`), mixed text, empty input.
- `tests/backend/modules/user/test_recent_emojis.py`: pure `_merge_lru`
  unit tests — front-loading, dedup, six-cap, empty inputs, no-change
  detection.
- `tests/backend/modules/user/test_recent_emojis_integration.py`:
  end-to-end `UserService.touch_recent_emojis` exercising the Mongo
  update and the event publish (DB-dependent, runs in Docker only).

### Frontend (vitest)

- `frontend/src/features/chat/insertEmojiAtCursor.test.ts`: cursor at
  start, end, middle, before/after whitespace, before/after emoji.
- `frontend/src/features/chat/EmojiPickerPopover.test.tsx`: render path,
  lazy-load mocked, selection callback fired with the native emoji.

### Manual Verification (real-device, see memory
`manual_test_sections_in_specs`)

1. **Desktop Chromium 1920×1080**: open the picker via the in-textarea
   trigger; it appears anchored above the trigger. Select 😀 with the
   cursor in the middle of `"abcdef"` → result `"abc 😀 def"`.
2. **Desktop Firefox**: open the skin-tone selector, pick a darker tone,
   select 👍 → text shows `👍🏿`. Send the message; the LRU reorders so
   `👍🏿` is first.
3. **Mobile Chromium 375×667 (iPhone SE responsive)**: tap the cockpit
   emoji button. Picker appears above the cockpit bar. Tap back into the
   input — the picker closes.
4. **Multi-tab**: open two tabs as the same user; in tab A send
   `"Hi 🔥"`. Tab B's picker LRU shows 🔥 at the front without page
   reload.
5. **Initial login of a new user**: LRU shows 👍 ❤️ 😂 🤘 😊 🔥. Send a
   message containing 🥳 → 🥳 is now first; 🔥 falls off the end.
6. **Disconnect simulation** (DevTools → Network → Offline) with the
   picker open — emoji insertion still works locally; reconnect causes
   the queued LRU update to flow in.

## Open Questions

None at this stage — design is ready for implementation planning.

## Out of Scope

- Phase II reactions on existing messages (intentionally dropped — emojis
  in message text serve the same expressive purpose).
- Custom or uploaded emojis.
- Localised search (uses emoji-mart's bundled English search index).
- Per-conversation emoji styling.
