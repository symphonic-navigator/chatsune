# Persona Editor — Design Spec

## Overview

The Persona Editor is the primary interface for creating, viewing, editing, and managing AI personas in Chatsune. It consists of three interconnected components:

1. **Persona Cards** — portrait-format cards on the Personas Page, optimised for quickly continuing or starting conversations
2. **Persona Overlay** — a modal (consistent with Admin/User modals) for viewing and editing all persona details
3. **Supporting systems** — monogram generation, Kundalini chakra theming, drag-and-drop reordering

The design follows the "Ethereal" aesthetic: dark backgrounds, soft chakra-coloured glows, generous whitespace, serif + monospace typography.

---

## 1. Kundalini Chakra Colour System

Seven chakra colours serve as the visual identity system for personas. Each persona is assigned exactly one chakra colour by the user.

| Chakra | Enum Value | Hex | Sanskrit |
|--------|-----------|------|----------|
| Root | `root` | #EB5A5A | muladhara |
| Sacral | `sacral` | #E67E32 | svadhisthana |
| Solar Plexus | `solar` | #C9A84C | manipura |
| Heart | `heart` | #4CB464 | anahata |
| Throat | `throat` | #508CDC | vishuddha |
| Third Eye | `third_eye` | #8C76D7 | ajna |
| Crown | `crown` | #A05AC8 | sahasrara |

The backend stores the enum value (e.g. `"root"`), not the hex code. The frontend maps enum values to hex codes, glow colours, and gradient definitions.

### Chakra-to-Persona Conceptual Mapping (Internal Design Language)

This mapping is NOT exposed as UI navigation, but inspires subtle labels in the Overlay:

| Chakra | Persona Aspect |
|--------|---------------|
| Crown | LLM model (the "mind") |
| Third Eye | Reasoning / temperature |
| Throat | System prompt (the "voice") |
| Heart | Memories (the relationship) |
| Solar Plexus | Name, tagline, personality |
| Sacral | NSFW / creative freedoms |
| Root | Knowledge libraries (the foundation) |

Sanskrit names appear as subtle secondary labels on the Knowledge, Memories, and History tabs in the Overlay (not on Overview or Edit — those are too "meta" for a chakra association).

---

## 2. Persona Card

### Format & Dimensions

- Portrait orientation
- Responsive width: `clamp`-based sizing, similar to old prototype (~200px base)
- Border-radius: ~24px
- Background: dark base with subtle chakra-coloured gradient at top

### Visual Elements (top to bottom)

1. **NSFW indicator** — top-left, kiss mark symbol (💋), reduced opacity. Only shown when persona is NSFW.
2. **Monogram badge** — top-right, monospace font, chakra colour at reduced opacity, small bordered pill. Always visible, even when a profile image is present.
3. **Avatar** — centred, circular (~100-120px), with radial gradient glow in chakra colour.
   - With profile image: displays the image
   - Without profile image: displays monogram in serif font (Lora) with chakra-coloured glow background
4. **Name** — serif font (Lora), light text (#e8e0d4)
5. **Tagline** — monospace, dimmed, uppercase, letter-spaced
6. **Overlay trigger** — small circular button with diamond symbol (⟡), centred, between info and action zones
7. **Action zones** — bottom strip, separated from card body by subtle horizontal line:
   - Left 2/3: "continue" with arrow icon — resumes last conversation. If no previous conversation exists, behaves identically to "new" (starts a fresh conversation).
   - Right 1/3: "new" with plus icon — starts fresh conversation
   - Separated by subtle vertical line
   - Both zones always visible (not hover-dependent)
   - Monospace labels, uppercase, letter-spaced

### Interactions

- **Hover**: gentle lift (`translateY(-8px)`, `scale(1.02)`), enhanced chakra glow shadow
- **Entrance animation**: staggered fade-in from below (`animation-delay: index * 0.15s`)
- **Drag & drop**: smooth reordering — grabbed card elevates with enhanced shadow, other cards animate to make space with CSS transitions (not hard repositioning). Uses dnd-kit with `rectSortingStrategy`.

### Add Persona Card

- Last slot in the grid
- Dashed border in gold (#C9A84C)
- Plus icon + "add persona" text
- Click opens the Overlay directly on the Edit tab (new persona)

---

## 3. Monogram Algorithm

A two-letter identifier generated per persona, unique within each user's persona set. Stored in the database, not computed on-the-fly.

### Generation Rules (in order of precedence)

1. **Multi-part name**: first initial + last initial, uppercase. "John von Neumann" → "JN", "Lara Croft" → "LC"
2. **Single-part name OR collision with existing monogram**: try letter combinations from the name (first two, first + third, etc.)
3. **No Latin letters in name** (e.g. special character usernames): iterate through "AA", "AB", "AC"...
4. Uniqueness is enforced **per user only** — different users may share monograms

### Lifecycle

- Generated on persona creation
- Regenerated on persona rename (may change)
- Deletion of a persona frees the monogram for future use
- Stored as `monogram` field in `PersonaDocument`

---

## 4. Persona Overlay

A modal overlay consistent in dimensions, styling, and behaviour with the existing Admin Modal and User Modal.

### Opening Contexts

1. **From Personas Page**: the card animates/expands into the modal. The card grows from its position to the modal's centred position with a smooth transition.
2. **From Chat**: opens directly as a standard modal (same animation as Admin/User modal, no card expansion).

### Dimensions & Styling

- Same width, max-height, border-radius, and backdrop-blur as Admin/User Modal
- Dark gradient background
- Border in chakra colour (subtle opacity)
- Chakra-coloured glow accents

### Tabs

#### 4.1 Overview (Default when opened from Chat)

- Large profile image or monogram fallback with chakra glow
- Name, tagline (full display)
- Statistics:
  - Number of chats
  - Consolidated memory tokens
  - Pending journal entries ("not yet consolidated")
- Created date, last active date
- Chakra colour as visual accent element

#### 4.2 Edit (Default when opened via Edit action from Personas Page)

- Name (text input)
- Tagline (text input)
- Chakra colour picker (7 circles representing the chakra colours)
- Model selection (triggers Model Selection Modal)
- System prompt (textarea)
- Temperature (slider, 0-2, step 0.05)
- Reasoning toggle (conditional on model capability)
- NSFW toggle
- Profile image upload/remove

#### 4.3 Knowledge / *muladhara*

- List of assigned knowledge libraries
- Add/remove libraries (library-level assignment only, not individual files)
- Subtle "muladhara" label

#### 4.4 Memories / *anahata*

- View consolidated memory
- View memory journal (pending entries)
- Future: "Dream" function (consolidation trigger)
- Subtle "anahata" label

#### 4.5 History / *vishuddha*

- Past conversations, chronological
- Grouped by project (persona can participate in multiple projects, n:m relationship — each project shows only conversations with this specific persona)
- Click on a conversation opens it in Chat
- Subtle "vishuddha" label

---

## 5. Personas Page

- **Layout**: responsive CSS grid (`auto-fit`, `minmax`-based), cards flow naturally
- **Background**: dark base (#0a0810), optional subtle nebula blobs (more restrained than old prototype)
- **No page title**: "Chatsune" is already visible in the sidebar — no redundancy
- **Sorting**: drag & drop with smooth animated reordering
- **Add card**: last slot, opens Overlay on Edit tab
- **NSFW filtering**: when Sanitised Mode is active, NSFW persona cards are hidden

---

## 6. Sidebar Integration

### Pinned Personas

- Pinned personas appear in the expanded sidebar as a compact list
- Display: small avatar (monogram or profile image) + name, chakra-coloured accent
- Click navigates to last chat with that persona (continue behaviour)
- Context menu includes "Persona" option to open the Overlay

### Sanitised Mode ("Hugo Portisch Mode")

When Sanitised Mode is activated, ALL NSFW-related content is immediately hidden (no reload required):

- Pinned NSFW personas disappear from sidebar
- Chat history entries from NSFW personas disappear from sidebar
- NSFW projects disappear from sidebar
- NSFW persona cards disappear from Personas Page

One toggle, everything clean.

---

## 7. Data Model Changes

### PersonaDocument (Backend)

New fields:
- `monogram: str` — generated two-letter identifier, unique per user
- `pinned: bool` — whether persona appears in sidebar (default: `false`)
- `profile_image: str | None` — path/URL to uploaded profile image (default: `None`)

Changed fields:
- `colour_scheme: str` — changes from free-form hex to chakra enum value. Valid values: `"root"`, `"sacral"`, `"solar"`, `"heart"`, `"throat"`, `"third_eye"`, `"crown"`. Default: `"solar"` (gold, matching existing brand accent).

### PersonaDto / CreatePersonaDto / UpdatePersonaDto (Shared)

Mirror the backend changes:
- Add `monogram` (read-only in DTO, never set by client)
- Add `pinned`
- Add `profile_image`
- Change `colour_scheme` type from free string to chakra enum

### Frontend Types

- `PersonaDto` interface updated to match
- New `ChakraColour` type/enum with the 7 values
- New `CHAKRA_PALETTE` constant mapping enum values to hex, glow, gradient definitions

---

## 8. Out of Scope

These are explicitly NOT part of this spec:

- Chat UI itself (separate spec)
- Knowledge library management (separate feature — this spec only covers assigning existing libraries to a persona)
- Memory consolidation / "Dream" function (separate feature — this spec only shows the read view)
- Project management (separate feature — History tab displays project groupings but does not manage them)
- Profile image storage backend (upload mechanism, file storage, CDN — separate concern, this spec assumes an endpoint exists)
