# Persona Card Redesign

## Summary

Redesign the persona cards to fix layout bugs (overlapping text), improve usability
(clear click zones, dedicated drag handle), and streamline navigation (bottom menu
opening the existing overlay). Additionally, suggest a random colour for new personas.

## Card Layout (top to bottom)

### Drag Handle

- Visible grip icon (6 dots, 2x3 grid) in the top-left corner
- Always visible (touch-friendly)
- Only this element is the drag handle — the rest of the card is not draggable
- Replaces current behaviour where the entire card is the drag handle

### Name

- Centred at the top of the card, below the drag handle area
- `font-size: 15px`, `font-weight: 600`

### Avatar / Monogram

- Fixed centre position using CSS Grid (`grid-template-rows: auto 1fr auto`)
- The avatar sits in the `1fr` row with `align-self: center` — its position never shifts
- 90px circle with the persona's chakra colour as border and glow
- Displays the monogram as fallback (later: profile image)

### Tagline

- Anchored to the bottom of the content area, directly above the chat zone labels
- Grows upward if needed, but limited to **2 lines maximum**
- Overflow handled with `-webkit-line-clamp: 2` and `text-overflow: ellipsis`
- `font-size: 11px`, italic, muted colour

## Chat Interaction Zones

The entire card area above the menu bar is clickable for chat actions.

### Zone Split

- Vertical divider at the 2/3 mark
- **Left zone** (flex: 2): "Continue" — resumes the most recent chat session
- **Right zone** (flex: 1): "New" — starts a new chat session

### Hover Behaviour

- **Card hover**: enhanced glow/border on the entire card, divider line fades in
- **Zone hover**: ghost labels ("CONTINUE" / "NEW") that are nearly invisible at rest
  glow in the persona's chakra colour when the user hovers over that zone
- Approach A style: labels only, no zone background highlight

### Navigation

- "Continue" navigates to `/chat/{personaId}`
- "New" navigates to `/chat/{personaId}?new=1`

## Menu Bar (bottom)

Three equally-sized buttons at the bottom of the card:

| Button   | Action                                          |
|----------|-------------------------------------------------|
| Overview | Opens PersonaOverlay on the `overview` tab       |
| Edit     | Opens PersonaOverlay on the `edit` tab           |
| History  | Opens PersonaOverlay on the `history` tab        |

- Separated by a subtle top border from the card content
- Hover effect: text colour changes to persona's chakra colour, subtle background tint
- These buttons use `onPointerDown(e.stopPropagation())` to prevent triggering drag

## Random Colour on Persona Creation

When creating a new persona, suggest a colour automatically:

### Algorithm: Least-Used First

1. Count how many existing personas use each of the 7 chakra colours
2. Find the minimum count
3. Collect all colours that have that minimum count
4. Pick one at random from that set

This ensures maximum visual diversity. When all colours are equally used (or no
personas exist yet), it falls back to a fully random pick.

### Scope

- Only on creation — the `DEFAULT_PERSONA` in `PersonaOverlay.tsx` currently
  hardcodes `colour_scheme: 'heart'`; this will be replaced with the algorithm
- On edit, the existing colour is preserved (user can still change it manually)

## Files to Modify

- `frontend/src/app/components/persona-card/PersonaCard.tsx` — full rewrite of card layout and interaction
- `frontend/src/app/components/persona-card/AddPersonaCard.tsx` — adjust dimensions if needed
- `frontend/src/app/pages/PersonasPage.tsx` — update handlers for overlay opening, fix continue vs new navigation
- `frontend/src/app/components/persona-overlay/PersonaOverlay.tsx` — replace hardcoded default colour with least-used algorithm
- `frontend/src/app/layouts/AppLayout.tsx` — no changes expected (overlay opening already supported)

## Out of Scope

- Profile image upload (avatar remains monogram-only for now)
- Changes to the PersonaOverlay tabs themselves
- Changes to the sidebar PersonaItem component
- Responsive/mobile-specific adaptations beyond touch-friendly drag handle
