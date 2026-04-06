# UX-008 & UX-009: Message Action Bar + Sidebar Flyout Panel

**Date:** 2026-04-06
**Status:** Approved
**Scope:** Frontend-only changes

---

## Problem Statement

### UX-008: Message actions unreachable on touch devices

Copy and bookmark buttons on chat messages are only visible on hover and positioned
absolutely outside the message bubble (`-right-8` / `-left-8`). On touch devices there
is no hover state, making these actions completely unreachable. On narrow screens the
buttons may overflow the visible area.

### UX-009: Inconsistent sidebar navigation paradigm

In expanded mode, Projects and History are inline collapsible sections in the sidebar.
In collapsed mode, the same icons open the UserModal as a full overlay. Two fundamentally
different interaction patterns for the same function.

---

## Design: UX-008 — Permanent Action Bar

### Approach

Replace the hover-only absolutely-positioned buttons with a permanent action strip
inside each message bubble, below the message text. Inspired by Grok's message actions.

### Specification

**Layout:**
- Action bar sits inside the message bubble, below the content
- Separated from content by a subtle divider (`border-top: 1px solid white/6`)
- `margin-top: 10px`, `padding-top: 8px`
- Actions laid out as `flex` row with `gap: 12px`

**Buttons:**
- Each button: icon (13x13 SVG) + text label
- Base colour: `text-white/25` (low contrast, does not compete with message)
- Hover colour: `text-white/50`
- Font size: 11px
- No background, no border — minimal footprint

**Actions per message type:**
- **AssistantMessage:** Copy, Bookmark
- **UserBubble:** Edit, Bookmark

**Bookmark state:**
- Unbookmarked: default styling (`text-white/25`)
- Bookmarked: gold colour (`text-gold`) with filled bookmark icon

**What to remove:**
- Remove the `absolute -right-8` / `-left-8` positioned button containers
- Remove the `group-hover` visibility logic
- Remove the `isHovered` dependency for showing action buttons

### Files to modify

- `frontend/src/features/chat/AssistantMessage.tsx` — replace hover buttons with inline action bar
- `frontend/src/features/chat/UserBubble.tsx` — replace hover buttons with inline action bar

### Consideration: Shared component

Both message types use near-identical action button markup. A shared `MessageActions`
component could reduce duplication. However, the action sets differ (Copy vs Edit), so
keep it simple: inline the action bar in each component. If a third message type appears
later, extract then.

---

## Design: UX-009 — Sidebar Flyout Panel

### Approach

When the sidebar is collapsed and the user clicks the Projects or History icon, a flyout
panel slides out from the sidebar edge instead of opening the UserModal. The flyout shows
the same content as the expanded sidebar sections. A button in the flyout header navigates
to the UserModal for full management.

### Specification

**Trigger:**
- Click on Projects icon in collapsed sidebar -> opens Projects flyout
- Click on History icon in collapsed sidebar -> opens History flyout
- All other collapsed sidebar icons (Knowledge, Bookmarks, Uploads, Artefacts, user avatar)
  continue to open the UserModal directly — they have no inline sidebar equivalent

**Flyout panel:**
- Width: 260px
- Background: `bg-[#1a1a30]` or matching sidebar panel colour from existing theme
- Positioned adjacent to the 50px collapsed sidebar (left: 50px)
- Box shadow on the right edge for depth (`shadow-xl`)
- Slide-in animation (CSS transition, ~200ms)

**Flyout header:**
- Title: "History" or "Projects" (uppercase, 12px, font-weight 600)
- "Open full view" button: opens UserModal at the corresponding tab
- Close button (X icon)

**Flyout content:**
- **History flyout:** Pinned sessions section + Recent sessions section.
  Same data and layout as the expanded sidebar History section.
  Sessions are clickable to navigate to the chat.
- **Projects flyout:** Project list or empty state with "Create project" button.
  Same data and layout as the expanded sidebar Projects section.

**Backdrop:**
- Dimmed overlay behind the flyout over the main content area
- Click on backdrop closes the flyout
- Escape key closes the flyout

**Close behaviour:**
- X button in header
- Backdrop click
- Escape key
- Navigating to a session (auto-close after navigation)

**Active state:**
- The triggering icon in the collapsed sidebar shows gold highlight when flyout is open
  (same `isTabActive` pattern already used)

### State management

- New state: `flyoutTab: 'projects' | 'history' | null` in the Sidebar component
- When `flyoutTab` is set, render the flyout panel
- Clicking the same icon again closes the flyout (toggle behaviour)
- "Open full view" sets `flyoutTab = null` and calls `onOpenModal(tab)`

### Files to modify

- `frontend/src/app/components/sidebar/Sidebar.tsx` — add flyout state, modify collapsed
  mode icon handlers for Projects/History, render flyout panel
- Optionally extract `SidebarFlyout.tsx` if the Sidebar file becomes too large

### What NOT to change

- Expanded sidebar behaviour stays exactly as-is
- UserModal stays as-is
- Other collapsed sidebar icons keep opening the UserModal
- No backend changes required

---

## Testing

### UX-008
- Verify action bar visible without hovering on both message types
- Verify Copy button works (copies to clipboard, shows checkmark feedback)
- Verify Bookmark button works (toggles state, gold when bookmarked)
- Verify Edit button works on user messages
- Verify action bar does not show during streaming
- Verify visual appearance matches design (low contrast, inside bubble)

### UX-009
- Verify Projects/History icons open flyout in collapsed mode
- Verify flyout shows correct content (sessions, projects)
- Verify "Open full view" opens UserModal at correct tab
- Verify close mechanisms: X button, backdrop click, Escape key
- Verify clicking a session navigates and closes the flyout
- Verify toggle: clicking same icon closes flyout
- Verify other icons (Knowledge, Bookmarks, etc.) still open UserModal
- Verify expanded sidebar behaviour is unchanged
