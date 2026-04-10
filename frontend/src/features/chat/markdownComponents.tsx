import { useCallback, useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react"
import type { Components } from "react-markdown"
import type { Highlighter } from "shiki"
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import 'katex/dist/katex.min.css'

import type { PluggableList } from 'unified'

export const remarkPlugins: PluggableList = [remarkGfm, remarkMath]
export const rehypePlugins: PluggableList = [[rehypeKatex, { throwOnError: false }]]

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
