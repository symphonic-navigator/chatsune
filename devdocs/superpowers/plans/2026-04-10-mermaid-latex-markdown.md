# Mermaid and LaTeX Markdown Support — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add inline Mermaid diagram rendering and LaTeX math rendering to all markdown render locations (chat, artefact preview, document editor).

**Architecture:** Extend the existing react-markdown plugin pipeline with `remark-math` + `rehype-katex` for LaTeX and a custom `MermaidBlock` component for ` ```mermaid ` code blocks. All configuration is centralised in `markdownComponents.tsx` and consumed by all three render locations.

**Tech Stack:** react-markdown, remark-math, rehype-katex, katex, mermaid (already installed)

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `frontend/package.json` | Modify | Add remark-math, rehype-katex, katex dependencies |
| `frontend/src/features/chat/markdownComponents.tsx` | Modify | Export plugin arrays, add MermaidBlock component, route mermaid code blocks |
| `frontend/src/features/chat/AssistantMessage.tsx` | Modify | Use central plugin config |
| `frontend/src/features/artefact/ArtefactPreview.tsx` | Modify | Use central plugin config in MarkdownPreview |
| `frontend/src/app/components/user-modal/DocumentEditorModal.tsx` | Modify | Use central plugin config |
| `frontend/src/index.css` | Modify | KaTeX dark-theme overrides |

---

### Task 1: Install dependencies

**Files:**
- Modify: `frontend/package.json`

- [ ] **Step 1: Install remark-math, rehype-katex, and katex**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm add remark-math rehype-katex katex
```

- [ ] **Step 2: Install katex types**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm add -D @types/katex
```

- [ ] **Step 3: Verify installation**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm ls remark-math rehype-katex katex
```

Expected: all three packages listed with versions.

- [ ] **Step 4: Commit**

```bash
git add frontend/package.json frontend/pnpm-lock.yaml
git commit -m "Add remark-math, rehype-katex, and katex for LaTeX support"
```

---

### Task 2: Export central plugin arrays from markdownComponents.tsx

**Files:**
- Modify: `frontend/src/features/chat/markdownComponents.tsx:1-3`

- [ ] **Step 1: Add plugin imports and exports**

At the top of `markdownComponents.tsx`, add the plugin imports and CSS import, then export the plugin arrays. The existing imports stay.

```typescript
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export const remarkPlugins = [remarkGfm, remarkMath]
export const rehypePlugins = [[rehypeKatex, { throwOnError: false }]]
```

Note: `rehypePlugins` uses the array-with-options syntax to pass `throwOnError: false` to rehype-katex. This makes invalid LaTeX render as red-tinted source text instead of throwing.

- [ ] **Step 2: Verify the file compiles**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/features/chat/markdownComponents.tsx
git commit -m "Export central remark/rehype plugin arrays for LaTeX support"
```

---

### Task 3: Add MermaidBlock component to markdownComponents.tsx

**Files:**
- Modify: `frontend/src/features/chat/markdownComponents.tsx:70-127`

- [ ] **Step 1: Add MermaidBlock component**

Add a new `MermaidBlock` component before the `createMarkdownComponents` function (before line 70). This component:
- Lazy-loads mermaid (reusing the same lazy pattern from `ArtefactPreview.tsx:220-224`)
- Uses `useEffect` + `useState` for async rendering
- Generates a unique ID per instance (required by mermaid API)
- On success: renders the SVG (mermaid produces sanitised SVG via its built-in DOMPurify)
- On error: shows raw source code with `title` tooltip containing the error

```typescript
let mermaidPromise: Promise<typeof import('mermaid')> | null = null
function loadMermaid(): Promise<typeof import('mermaid')> {
  if (!mermaidPromise) mermaidPromise = import('mermaid')
  return mermaidPromise
}

function MermaidBlock({ code }: { code: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [svg, setSvg] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false

    loadMermaid().then((mod) => {
      if (cancelled) return
      const mermaid = mod.default
      mermaid.initialize({ startOnLoad: false, theme: 'dark' })

      const id = `mermaid-inline-${Math.random().toString(36).slice(2)}`
      mermaid
        .render(id, code)
        .then(({ svg: rendered }) => {
          if (!cancelled) {
            setSvg(rendered)
            setError(null)
          }
        })
        .catch((err: unknown) => {
          if (!cancelled) {
            setError(err instanceof Error ? err.message : 'Failed to render diagram')
          }
        })
    })

    return () => { cancelled = true }
  }, [code])

  if (error) {
    return (
      <div className="relative" title={error}>
        <pre className="overflow-x-auto rounded-lg bg-elevated p-4 text-[13px] border border-amber-500/20">
          <code>{code}</code>
        </pre>
      </div>
    )
  }

  if (!svg) {
    return (
      <div className="flex items-center justify-center rounded-lg bg-elevated p-8">
        <span className="text-[12px] text-white/30 font-mono">Rendering diagram...</span>
      </div>
    )
  }

  // Mermaid render() output is sanitised via its built-in DOMPurify integration
  // (same approach as existing MermaidPreview in ArtefactPreview.tsx:248)
  return (
    <div
      ref={containerRef}
      className="my-2 flex justify-center overflow-x-auto rounded-lg bg-elevated p-4 [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}
```

- [ ] **Step 2: Route mermaid code blocks to MermaidBlock**

In the `createMarkdownComponents` function, add a check for `language-mermaid` before the existing Shiki highlighting logic. After the existing inline code return (line 83 area), add:

```typescript
if (lang === 'mermaid') {
  return <MermaidBlock code={codeStr} />
}
```

This goes right after the `if (!lang)` block (which returns inline code) and before the `if (highlighter)` block.

- [ ] **Step 3: Add required imports**

The file already imports `useState` and `useRef` from the existing code. Verify `useEffect` is also in the import. Update the import line at the top:

```typescript
import { useCallback, useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react"
```

(`useCallback` is already there, `useEffect` needs to be added.)

- [ ] **Step 4: Verify the file compiles**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/features/chat/markdownComponents.tsx
git commit -m "Add MermaidBlock component for inline mermaid code blocks"
```

---

### Task 4: Update AssistantMessage.tsx to use central plugins

**Files:**
- Modify: `frontend/src/features/chat/AssistantMessage.tsx:2-3,39`

- [ ] **Step 1: Replace plugin imports**

Replace:
```typescript
import remarkGfm from 'remark-gfm'
```

With:
```typescript
import { remarkPlugins, rehypePlugins } from './markdownComponents'
```

- [ ] **Step 2: Update ReactMarkdown usage**

Replace line 39:
```tsx
<ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
```

With:
```tsx
<ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={components}>
```

- [ ] **Step 3: Verify compilation**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/chat/AssistantMessage.tsx
git commit -m "Use central markdown plugin config in AssistantMessage"
```

---

### Task 5: Update ArtefactPreview.tsx MarkdownPreview to use central plugins

**Files:**
- Modify: `frontend/src/features/artefact/ArtefactPreview.tsx:3,20-22`

- [ ] **Step 1: Replace plugin imports**

Replace:
```typescript
import remarkGfm from 'remark-gfm'
```

With:
```typescript
import { remarkPlugins, rehypePlugins } from '../chat/markdownComponents'
```

- [ ] **Step 2: Update MarkdownPreview ReactMarkdown usage**

Replace lines 20-22:
```tsx
<ReactMarkdown
  remarkPlugins={[remarkGfm]}
  components={components}
>
```

With:
```tsx
<ReactMarkdown
  remarkPlugins={remarkPlugins}
  rehypePlugins={rehypePlugins}
  components={components}
>
```

- [ ] **Step 3: Verify compilation**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/features/artefact/ArtefactPreview.tsx
git commit -m "Use central markdown plugin config in ArtefactPreview"
```

---

### Task 6: Update DocumentEditorModal.tsx to use central plugins

**Files:**
- Modify: `frontend/src/app/components/user-modal/DocumentEditorModal.tsx:3,217`

- [ ] **Step 1: Replace plugin imports**

Replace:
```typescript
import remarkGfm from 'remark-gfm'
```

With:
```typescript
import { remarkPlugins, rehypePlugins } from '../../../features/chat/markdownComponents'
```

- [ ] **Step 2: Update ReactMarkdown usage**

Replace line 217:
```tsx
<ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
```

With:
```tsx
<ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
```

- [ ] **Step 3: Verify compilation**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm tsc --noEmit
```

Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/app/components/user-modal/DocumentEditorModal.tsx
git commit -m "Use central markdown plugin config in DocumentEditorModal"
```

---

### Task 7: Add KaTeX dark-theme CSS overrides

**Files:**
- Modify: `frontend/src/index.css:401` (after `.markdown-preview input[type="checkbox"]`)

- [ ] **Step 1: Add KaTeX colour overrides**

Add after the `.markdown-preview input[type="checkbox"]` rule (line 401), before the artefact-scroll section:

```css
/* KaTeX dark-theme overrides — KaTeX defaults to black text */
.chat-prose .katex { color: rgba(255, 255, 255, 0.85); }
.chat-prose .katex .mord,
.chat-prose .katex .mbin,
.chat-prose .katex .mrel,
.chat-prose .katex .mopen,
.chat-prose .katex .mclose,
.chat-prose .katex .mpunct,
.chat-prose .katex .minner { color: inherit; }
.chat-prose .katex-display { margin: 0.75em 0; overflow-x: auto; }

.markdown-preview .katex { color: rgba(232, 224, 212, 0.85); }
.markdown-preview .katex .mord,
.markdown-preview .katex .mbin,
.markdown-preview .katex .mrel,
.markdown-preview .katex .mopen,
.markdown-preview .katex .mclose,
.markdown-preview .katex .mpunct,
.markdown-preview .katex .minner { color: inherit; }
.markdown-preview .katex-display { margin: 0.75em 0; overflow-x: auto; }
```

- [ ] **Step 2: Verify build**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm run build
```

Expected: clean build, no errors.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/index.css
git commit -m "Add KaTeX dark-theme colour overrides for chat and artefact preview"
```

---

### Task 8: Full build verification

- [ ] **Step 1: Clean build**

```bash
cd /home/chris/workspace/chatsune/frontend && pnpm run build
```

Expected: clean build with no errors.

- [ ] **Step 2: Final commit (if any remaining changes)**

```bash
git status
```

If clean, no action needed.
