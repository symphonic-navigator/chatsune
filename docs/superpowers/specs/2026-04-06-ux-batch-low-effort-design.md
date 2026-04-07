# Low-Effort UX Batch — Design Spec

**Date:** 2026-04-06
**Status:** Approved
**Addresses:** UX-010, UX-011, UX-014, UX-015

---

## UX-010: GEN Button Feedback

**Files:** `frontend/src/app/components/user-modal/HistoryTab.tsx`, `frontend/src/app/components/persona-overlay/HistoryTab.tsx`

**Current:** GEN button shows "..." for a hardcoded 2-second timeout regardless of whether title generation succeeded.

**Fix:** Replace the 2-second timeout with event-driven feedback:
- On click: show "..." and disable button (as now)
- When `CHAT_SESSION_TITLE_UPDATED` event arrives for this session: show "OK" for 1 second, then revert to "GEN"
- Fallback: if no event arrives within 10 seconds, silently revert to "GEN"
- Both HistoryTab components get the same fix

---

## UX-011: SURE? Confirmation — Remove Timer, Use Outside-Click

**Files:** `frontend/src/app/components/user-modal/HistoryTab.tsx`, `frontend/src/app/components/user-modal/BookmarksTab.tsx`

**Current:** SURE? button appears for 3 seconds then silently reverts to DEL. No visual feedback that it will disappear.

**Fix:** Remove the 3-second timer entirely. The SURE? state persists until:
- User clicks SURE? (confirms deletion)
- User clicks elsewhere (outside-click reverts to DEL)
- User scrolls or interacts with another item

Implementation: remove `setTimeout` from `startDeleteConfirm`. Add a `useEffect` that listens for `mousedown` on `document` and resets `confirmDelete` to `false` if the click target is outside the SURE? button. Clean up on unmount.

Note: `HistoryItem.tsx` (sidebar) already works this way — no timer, menu closes on outside-click. Only the modal variants need fixing.

---

## UX-014: ContextStatusPill — Show "CTX" Label in Green State

**File:** `frontend/src/features/chat/ContextStatusPill.tsx`

**Current:** In green state, only a tiny green dot is shown. No label, no percentage.

**Fix:** Always show "CTX" as the label text next to the dot. Show percentage from yellow onwards (as currently). This makes the element identifiable without hovering.

Change: remove the `showPercentage` conditional for the label. Always render a text span:
- Green: `CTX`
- Yellow/Orange/Red: `CTX {pct}%`

---

## UX-015: Reasoning Toggle — Mark as Already Fixed

**File:** `frontend/src/features/chat/ToolToggles.tsx`

The button is already conditionally rendered with `{modelSupportsReasoning && ...}`. When the model doesn't support reasoning, the button is not shown at all. The original UX debt item was based on an older implementation. Mark as already fixed in UX-DEBT.md.
