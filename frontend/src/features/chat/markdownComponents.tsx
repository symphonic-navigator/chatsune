import { useCallback, useState, type ComponentPropsWithoutRef } from "react"
import type { Components } from "react-markdown"
import type { Highlighter } from "shiki"

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false)

  const handleCopy = useCallback(() => {
    navigator.clipboard.writeText(text)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }, [text])

  return (
    <button
      type="button"
      onClick={handleCopy}
      className="absolute right-2 top-2 rounded border border-white/10 bg-white/5 px-2 py-0.5 font-mono text-[11px] text-white/40 transition-colors hover:bg-white/10 hover:text-white/60"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  )
}

export function createMarkdownComponents(highlighter: Highlighter | null): Components {
  return {
    code(props: ComponentPropsWithoutRef<"code">) {
      const { children, className, ...rest } = props
      const match = /language-(\w+)/.exec(className || "")
      const lang = match?.[1]
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
          html = `<pre><code>${codeStr}</code></pre>`
        }

        return (
          <div className="relative">
            <CopyButton text={codeStr} />
            <div
              className="overflow-x-auto rounded-lg text-[13px] [&_pre]:!bg-[#1a1528] [&_pre]:p-4"
              dangerouslySetInnerHTML={{ __html: html }}
            />
          </div>
        )
      }

      return (
        <div className="relative">
          <CopyButton text={codeStr} />
          <pre className="overflow-x-auto rounded-lg bg-elevated p-4 text-[13px]">
            <code>{codeStr}</code>
          </pre>
        </div>
      )
    },
  }
}
