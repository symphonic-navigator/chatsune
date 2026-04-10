# Mermaid and LaTeX Support in Markdown Renderer

**Date:** 2026-04-10
**Status:** Approved

---

## Summary

Add Mermaid diagram rendering and LaTeX math rendering to the shared markdown
pipeline. Both features apply everywhere markdown is rendered: chat messages
(AssistantMessage), artefact markdown preview (ArtefactPreview), and the
document editor preview (DocumentEditorModal).

---

## Requirements

1. **LaTeX math** renders inline (`$...$`, `\(...\)`) and block (`$$...$$`, `\[...\]`)
2. **Mermaid diagrams** render from ` ```mermaid ` code blocks inline in markdown
3. Both work in all three markdown render locations (chat, artefact preview, document editor)
4. Error handling: fallback to raw source text with hover tooltip showing the error
5. Theming: consistent with existing dark theme

---

## Dependencies

### New packages

| Package | Purpose | Licence |
|---|---|---|
| `remark-math` | Recognises math syntax in markdown AST | MIT |
| `rehype-katex` | Renders math nodes to HTML via KaTeX | MIT |
| `katex` | Peer dependency of rehype-katex, provides CSS | MIT |

### Already installed

| Package | Version | Used for |
|---|---|---|
| `mermaid` | 11.14.0 | Diagram rendering (currently only in ArtefactPreview) |
| `remark-gfm` | 4.0.1 | GitHub Flavoured Markdown |
| `react-markdown` | 10.1.0 | Markdown renderer |

---

## Architecture

### Central plugin configuration

A single file (`markdownComponents.tsx`) exports the plugin arrays and all
custom components. All three render locations import from here.

```typescript
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

export const remarkPlugins = [remarkGfm, remarkMath]
export const rehypePlugins = [rehypeKatex]
```

### LaTeX rendering

- `remark-math` parses `$...$`, `$$...$$`, `\(...\)`, `\[...\]` into math AST nodes
- `rehype-katex` converts those nodes to rendered HTML
- Configuration: `throwOnError: false` -- invalid LaTeX renders as red-tinted source text
  (built-in KaTeX behaviour)
- KaTeX CSS imported once, with dark-theme overrides in `index.css`

### Mermaid rendering in code blocks

The existing `createMarkdownComponents` factory in `markdownComponents.tsx` is
extended. When a code block has `language-mermaid`, a `MermaidBlock` component
renders instead of the Shiki highlighter.

**MermaidBlock component:**

- Uses `useEffect` + `useState` for async `mermaid.render()` call
- Unique ID per instance (required by mermaid API)
- On success: renders SVG output from mermaid (mermaid generates sanitised SVG)
- On error: renders source as plain code block with `title` attribute containing
  the error message (hover tooltip)
- Mermaid theme: `dark` (consistent with existing MermaidPreview in ArtefactPreview)

**Security note:** Mermaid's `render()` produces sanitised SVG output by default
using its built-in DOMPurify integration. The existing `MermaidPreview` component
in the codebase already uses this same approach. KaTeX output is also safe by
design as it generates only math markup elements.

**Note:** The existing `MermaidPreview` component in `ArtefactPreview.tsx` remains
unchanged. It handles the "mermaid" artefact content type. The new `MermaidBlock`
is for ` ```mermaid ` code blocks inside markdown content.

### Error handling

| Feature | Error behaviour |
|---|---|
| KaTeX | `throwOnError: false` -- renders source text in error colour (built-in) |
| Mermaid | catch block shows raw source as code block + tooltip with error message |

### CSS changes

- Import `katex/dist/katex.min.css` (once, in markdownComponents.tsx)
- Dark-theme overrides in `index.css`: KaTeX defaults to black text, needs white
  for dark backgrounds. Applied within `.chat-prose` and `.markdown-preview` scopes

---

## Files changed

| File | Change |
|---|---|
| `frontend/package.json` | Add remark-math, rehype-katex, katex |
| `frontend/src/features/chat/markdownComponents.tsx` | Export plugin arrays, add MermaidBlock component, extend code component routing |
| `frontend/src/features/chat/AssistantMessage.tsx` | Import and use central remarkPlugins + rehypePlugins |
| `frontend/src/features/artefact/ArtefactPreview.tsx` | Import and use central remarkPlugins + rehypePlugins (MarkdownPreview only) |
| `frontend/src/app/components/user-modal/DocumentEditorModal.tsx` | Import and use central remarkPlugins + rehypePlugins |
| `frontend/src/index.css` | KaTeX dark-theme colour overrides |

---

## Out of scope

- LaTeX rendering in user messages (UserBubble uses plain text, not markdown)
- Mermaid artefact type changes (existing MermaidPreview stays as-is)
- Additional KaTeX macros or custom commands
- Mermaid click/interaction handlers
