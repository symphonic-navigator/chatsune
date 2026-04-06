import { useEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import type { Highlighter } from 'shiki'
import { createMarkdownComponents } from '../chat/markdownComponents'
import { useHighlighter } from '../chat/useMarkdown'
import type { ArtefactType } from '../../core/types/artefact'

// ─── Markdown ────────────────────────────────────────────────────────────────

function MarkdownPreview({ content, highlighter }: { content: string; highlighter: Highlighter | null }) {
  return (
    <div className="absolute inset-0 overflow-y-auto p-4">
      <div className="markdown-preview">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={createMarkdownComponents(highlighter)}
        >
          {content}
        </ReactMarkdown>
      </div>
    </div>
  )
}

// ─── Code ────────────────────────────────────────────────────────────────────

function CodePreview({ content, language, highlighter }: { content: string; language: string | null; highlighter: Highlighter | null }) {
  const lang = language ?? 'text'

  if (highlighter) {
    let html: string
    try {
      html = highlighter.codeToHtml(content, { lang, theme: 'github-dark-dimmed' })
    } catch {
      const escaped = content
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
      html = `<pre><code>${escaped}</code></pre>`
    }

    // html is Shiki library output, not user-controlled markup
    return (
      <div
        className="absolute inset-0 overflow-auto p-4 text-[13px] [&_pre]:!bg-transparent [&_pre]:p-0"
        dangerouslySetInnerHTML={{ __html: html }} // nosec: Shiki-generated, not user content
      />
    )
  }

  return (
    <pre className="absolute inset-0 overflow-auto p-4 text-[13px]">
      <code>{content}</code>
    </pre>
  )
}

// ─── HTML ────────────────────────────────────────────────────────────────────

function HtmlPreview({ content }: { content: string }) {
  return (
    <iframe
      srcDoc={content}
      sandbox="allow-scripts"
      className="absolute inset-0 border-0 bg-white rounded"
      title="HTML preview"
    />
  )
}

// ─── SVG ────────────────────────────────────────────────────────────────────

function SvgPreview({ content }: { content: string }) {
  const dataUri = `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(content)))}`

  return (
    <div className="absolute inset-0 flex items-center justify-center p-4">
      <img src={dataUri} alt="SVG preview" className="max-h-full max-w-full object-contain" />
    </div>
  )
}

// ─── JSX ────────────────────────────────────────────────────────────────────

const JSX_SANDBOX_HTML = (userCode: string) => `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>body { margin: 0; font-family: sans-serif; }</style>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
${userCode}

const root = ReactDOM.createRoot(document.getElementById('root'));
root.render(React.createElement(App));
  </script>
</body>
</html>`

function JsxPreview({ content }: { content: string }) {
  return (
    <iframe
      srcDoc={JSX_SANDBOX_HTML(content)}
      sandbox="allow-scripts"
      className="absolute inset-0 border-0 bg-white rounded"
      title="JSX preview"
    />
  )
}

// ─── Mermaid ────────────────────────────────────────────────────────────────

function MermaidPreview({ content }: { content: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    let cancelled = false

    import('mermaid').then((mod) => {
      if (cancelled) return
      const mermaid = mod.default

      mermaid.initialize({ startOnLoad: false, theme: 'dark' })

      const id = `mermaid-${Math.random().toString(36).slice(2)}`

      mermaid
        .render(id, content)
        .then(({ svg }) => {
          if (cancelled || !containerRef.current) return
          // svg is Mermaid library output, not user-controlled markup
          containerRef.current.innerHTML = svg // nosec: Mermaid-generated SVG
          setError(null)
        })
        .catch((err: unknown) => {
          if (cancelled) return
          setError(err instanceof Error ? err.message : 'Failed to render diagram')
        })
    })

    return () => {
      cancelled = true
    }
  }, [content])

  if (error) {
    return (
      <div className="absolute inset-0 flex items-center justify-center p-4">
        <div className="rounded border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          <div className="mb-1 font-semibold">Diagram parse error</div>
          <div className="font-mono text-xs opacity-80">{error}</div>
        </div>
      </div>
    )
  }

  return (
    <div
      ref={containerRef}
      className="absolute inset-0 flex items-center justify-center overflow-auto p-4 [&_svg]:max-h-full [&_svg]:max-w-full"
    />
  )
}

// ─── Main switcher ───────────────────────────────────────────────────────────

interface ArtefactPreviewProps {
  content: string
  type: ArtefactType
  language: string | null
}

export function ArtefactPreview({ content, type, language }: ArtefactPreviewProps) {
  const highlighter = useHighlighter()

  switch (type) {
    case 'markdown':
      return <MarkdownPreview content={content} highlighter={highlighter} />
    case 'code':
      return <CodePreview content={content} language={language} highlighter={highlighter} />
    case 'html':
      return <HtmlPreview content={content} />
    case 'svg':
      return <SvgPreview content={content} />
    case 'jsx':
      return <JsxPreview content={content} />
    case 'mermaid':
      return <MermaidPreview content={content} />
    default:
      return <CodePreview content={content} language={language} highlighter={highlighter} />
  }
}
