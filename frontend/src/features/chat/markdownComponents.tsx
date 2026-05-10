import { useCallback, useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react"
import type { Components } from "react-markdown"
import type { Highlighter } from "shiki"
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeVoiceTags from './rehypeVoiceTags'
import rehypeIntegrationPills from './rehypeIntegrationPills'
import rehypeKatex from 'rehype-katex'
import katex from 'katex'
import 'katex/dist/katex.min.css'

import type { PluggableList } from 'unified'

export const remarkPlugins: PluggableList = [remarkGfm, remarkMath]

/**
 * Build the rehype plugin list for a single render. Per-render input
 * (currently just `pillContents`) gets baked into the plugin options here,
 * so callers that want pill resolution must invoke this factory rather than
 * importing a static plugin array. Tests / non-pill renderers can omit
 * `pillContents` and the plugin becomes a no-op.
 *
 * Voice-tag pilling and KaTeX behave the same regardless of pill state, so
 * they are added unconditionally.
 */
export function buildRehypePlugins(
  opts: { pillContents?: Map<string, string> } = {},
): PluggableList {
  return [
    rehypeVoiceTags,
    [rehypeIntegrationPills, { pillContents: opts.pillContents ?? new Map<string, string>() }],
    [rehypeKatex, { throwOnError: false }],
  ]
}

/** Static plugin list retained for callers that don't render integration
 *  pills — equivalent to `buildRehypePlugins()` with no options. */
export const rehypePlugins: PluggableList = buildRehypePlugins()

/**
 * Preprocess markdown to normalise math delimiters that remark-math does not
 * handle natively:
 *   \( ... \)  →  $ ... $    (inline)
 *   \[ ... \]  →  $$ ... $$  (display)
 *
 * Runs before the string reaches ReactMarkdown so remark-math can parse them.
 *
 * Three concerns drive the implementation:
 *
 *   1. Multiline display math. micromark-extension-math only recognises
 *      `$$...$$` as a display fence when both `$$` markers stand at a line
 *      boundary; otherwise it falls back to inline-math parsing, which forbids
 *      newlines inside the content. So when the inner content of `\[...\]`
 *      contains a newline (matrices, aligned, cases, multi-line expressions)
 *      we emit a proper block fence with surrounding blank lines:
 *           \n\n$$\n<content>\n$$\n\n
 *      Single-line content keeps the compact `$$<content>$$` form so it still
 *      flows correctly inside list items, blockquotes, etc.
 *
 *   2. Code spans / code fences. The regex must not rewrite math syntax that
 *      a user typed inside a code span — that would silently corrupt their
 *      text. We mask code regions with a sentinel placeholder before the
 *      math substitutions run, then restore them afterwards.
 *
 *   3. `\\[Npt]` line-break-with-spacing inside aligned environments. The
 *      `\[` regex must not match the `[` of `\\[5pt]`. A negative-look-behind
 *      on `\` prevents the false match.
 */
export function preprocessMath(src: string): string {
  // Step 1 — mask code spans and fenced code blocks with a sentinel that the
  // math regexes will never match. NUL is safe because it is not allowed in
  // valid Markdown / HTML text.
  const masks: string[] = []
  const mask = (m: string): string => {
    const i = masks.length
    masks.push(m)
    return `\u0000CODE${i}\u0000`
  }
  let out = src
    // Fenced code blocks with ``` or ~~~ (anchored to a line boundary).
    .replace(/(^|\n)(```[\s\S]*?\n```|~~~[\s\S]*?\n~~~)/g, (_m, lead: string, fence: string) =>
      `${lead}${mask(fence)}`,
    )
    // Inline code with one or more backticks — `\1` ensures matched fence
    // length on both sides.
    .replace(/(`+)([\s\S]*?)\1/g, (m) => mask(m))

  // Step 2 — \[ ... \] → display math. Negative-look-behind on `\` prevents
  // \\[Npt] (LaTeX line-break with optional spacing) from matching.
  out = out.replace(/(?<!\\)\\\[([\s\S]*?)\\\]/g, (_m, inner: string) => {
    const trimmed = inner.trim()
    if (trimmed.includes('\n')) {
      return `\n\n$$\n${trimmed}\n$$\n\n`
    }
    return `$$${trimmed}$$`
  })

  // Step 3 — \( ... \) → inline math. Inner must be trimmed: remark-math v6
  // rejects inline math that starts or ends with whitespace (anti-currency
  // heuristic), so `$ x $` would not be recognised.
  out = out.replace(/(?<!\\)\\\(([\s\S]+?)\\\)/g, (_m, inner: string) => `$${inner.trim()}$`)

  // Step 4 — restore the masked code regions.
  out = out.replace(/\u0000CODE(\d+)\u0000/g, (_m, idx: string) => masks[Number(idx)])

  return out
}

const COLLAPSE_LINE_THRESHOLD = 15

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
  }, [])

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    if (timeoutRef.current) clearTimeout(timeoutRef.current)
    timeoutRef.current = setTimeout(() => setCopied(false), 1500)
  }, [text])

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="absolute right-2 top-2 z-10 rounded border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[11px] text-white/40 transition-colors hover:bg-white/10 hover:text-white/60"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

function CollapsibleCode({ codeStr, children }: { codeStr: string; children: React.ReactNode }) {
  const lineCount = codeStr.split("\n").length
  const [expanded, setExpanded] = useState(lineCount <= COLLAPSE_LINE_THRESHOLD)
  const isCollapsible = lineCount > COLLAPSE_LINE_THRESHOLD

  if (!isCollapsible) return <>{children}</>

  if (!expanded) {
    return (
      <div className="relative max-h-[240px] overflow-hidden">
        {children}
        <div className="absolute inset-x-0 bottom-0 h-16 bg-[#1a1528] lg:bg-gradient-to-t lg:from-[#1a1528] lg:to-transparent" />
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-white/10 bg-elevated lg:bg-elevated/80 px-3 py-1 font-mono text-[11px] text-white/50 lg:backdrop-blur-sm transition-colors hover:bg-white/10 hover:text-white/70"
        >
          {lineCount} lines — expand
        </button>
      </div>
    )
  }

  return (
    <>
      {children}
      <button
        type="button"
        onClick={() => setExpanded(false)}
        className="mt-1 w-full rounded-b-lg border border-white/6 bg-white/[0.02] py-1 font-mono text-[11px] text-white/30 transition-colors hover:text-white/50"
      >
        Collapse
      </button>
    </>
  )
}

let mermaidPromise: Promise<typeof import('mermaid')> | null = null
function loadMermaid(): Promise<typeof import('mermaid')> {
  if (!mermaidPromise) mermaidPromise = import('mermaid')
  return mermaidPromise
}

function MermaidBlock({ code }: { code: string }) {
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
  return (
    <div
      className="my-2 flex justify-center overflow-x-auto rounded-lg bg-elevated p-4 [&_svg]:max-w-full"
      dangerouslySetInnerHTML={{ __html: svg }}
    />
  )
}

/**
 * Strip outer math delimiters that LLMs often include inside a ```latex fence:
 *   $$ ... $$   →   ...
 *   \[ ... \]   →   ...
 *   \( ... \)   →   ...
 *   $ ... $     →   ...
 * KaTeX expects the raw expression without delimiters.
 */
function stripMathDelimiters(src: string): string {
  const trimmed = src.trim()
  const pairs: Array<[string, string]> = [
    ['$$', '$$'],
    ['\\[', '\\]'],
    ['\\(', '\\)'],
    ['$', '$'],
  ]
  for (const [open, close] of pairs) {
    if (trimmed.startsWith(open) && trimmed.endsWith(close) && trimmed.length >= open.length + close.length) {
      return trimmed.slice(open.length, trimmed.length - close.length).trim()
    }
  }
  return trimmed
}

function LatexBlock({ code }: { code: string }) {
  const expression = stripMathDelimiters(code)
  // katex.renderToString with throwOnError: false produces the error HTML itself
  // (red source display) rather than throwing — so no try/catch fallback is needed.
  const html = katex.renderToString(expression, { displayMode: true, throwOnError: false })

  // nosec: katex.renderToString produces sanitised library output, not user-controlled HTML
  return (
    <div
      className="my-2 overflow-x-auto"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}

export function createMarkdownComponents(highlighter: Highlighter | null): Components {
  return {
    code(props: ComponentPropsWithoutRef<"code">) {
      const { children, className, ...rest } = props
      const langMatch = className ? /language-(\w+)/.exec(className) : null
      const lang = langMatch?.[1]
      const codeStr = String(children).replace(/\n$/, "")

      if (!lang) {
        return (
          <code className={className} {...rest}>
            {children}
          </code>
        )
      }

      if (lang === 'mermaid') {
        return <MermaidBlock code={codeStr} />
      }

      if (lang === 'latex' || lang === 'tex') {
        return <LatexBlock code={codeStr} />
      }

      if (highlighter) {
        let html: string
        try {
          html = highlighter.codeToHtml(codeStr, {
            lang,
            theme: "github-dark-dimmed",
          })
        } catch {
          const escaped = codeStr
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
          html = `<pre><code>${escaped}</code></pre>`
        }

        return (
          <CollapsibleCode codeStr={codeStr}>
            <div className="relative">
              <CopyButton text={codeStr} />
              <div
                className="overflow-x-auto rounded-lg text-[13px] [&_pre]:!bg-[#1a1528] [&_pre]:p-4"
                dangerouslySetInnerHTML={{ __html: html }}
              />
            </div>
          </CollapsibleCode>
        )
      }

      return (
        <CollapsibleCode codeStr={codeStr}>
          <div className="relative">
            <CopyButton text={codeStr} />
            <pre className="overflow-x-auto rounded-lg bg-elevated p-4 text-[13px]">
              <code>{codeStr}</code>
            </pre>
          </div>
        </CollapsibleCode>
      )
    },
  }
}
