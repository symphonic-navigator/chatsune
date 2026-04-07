import { useCallback, useEffect, useRef, useState, type ComponentPropsWithoutRef } from "react"
import type { Components } from "react-markdown"
import type { Highlighter } from "shiki"

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
        <div className="absolute inset-x-0 bottom-0 h-16 bg-gradient-to-t from-[#1a1528] to-transparent" />
        <button
          type="button"
          onClick={() => setExpanded(true)}
          className="absolute bottom-2 left-1/2 -translate-x-1/2 rounded-full border border-white/10 bg-elevated/80 px-3 py-1 font-mono text-[11px] text-white/50 backdrop-blur-sm transition-colors hover:bg-white/10 hover:text-white/70"
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
