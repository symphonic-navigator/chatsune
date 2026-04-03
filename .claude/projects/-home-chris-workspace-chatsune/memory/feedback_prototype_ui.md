---
name: Frontend prototype UI feedback
description: Chris's feedback on the first prototype iteration - 8 improvement points for the next round
type: feedback
---

After first prototype test run, Chris identified these improvements:

1. **Auto-detect master admin** -- don't show "set up master admin" link, instead query backend `/api/auth/status` to determine if setup is needed. Previous prototype had this pattern.
2. **"LLM" -> "Models"** in sidebar nav -- purely cosmetic rename
3. **User list shows API key status** -- per-provider badges (green/red) showing which users have keys and if they work. Previous prototype had `ApiKeyBadges` component.
4. **Models fetchable without API key** -- Ollama Cloud doesn't require a key for model listing
5. **Settings logical layer** -- not raw key-value, but semantic settings (e.g. "system-wide system prompt")
6. **Model selector with filters** -- filter-based model picker for persona creation, reasoning toggle only shown when model supports it and auto-selected for reasoning models. Previous prototype had `ModelBrowser` with rich filters.
7. **API key test feedback** -- inline status badge (verified/failed/testing) + toast notification system. Previous prototype used inline status + Zustand notification store.
8. **Model list filter-based** -- instead of click-per-provider, use filters like the model browser

**Why:** Chris is weak on UI/UX by own admission, but has strong opinions from testing. These are real usability issues discovered through hands-on testing.

**How to apply:** These should be addressed in a second iteration of the prototype. Reference the previous prototype at `/home/chris/workspace/chat-client-02/frontend` for proven patterns.
