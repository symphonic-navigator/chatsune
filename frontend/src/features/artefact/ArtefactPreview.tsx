import { useEffect, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import type { Highlighter } from 'shiki'
import { createMarkdownComponents, remarkPlugins, rehypePlugins, preprocessMath } from '../chat/markdownComponents'
import { useHighlighter } from '../chat/useMarkdown'
import type { ArtefactType } from '../../core/types/artefact'

/** Shared style: fill the parent container with gold-accent scrollbar */
const FILL: React.CSSProperties = { width: '100%', height: '100%', overflow: 'auto' }
const FILL_CLS = 'artefact-scroll'

// ─── Markdown ────────────────────────────────────────────────────────────────

function MarkdownPreview({ content, highlighter }: { content: string; highlighter: Highlighter | null }) {
  const components = useMemo(() => createMarkdownComponents(highlighter), [highlighter])
  return (
    <div style={FILL} className={`${FILL_CLS} p-4`}>
      <div className="markdown-preview">
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={rehypePlugins}
          components={components}
        >
          {preprocessMath(content)}
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
        style={FILL}
        className={`${FILL_CLS} p-4 text-[13px] [&_pre]:!bg-transparent [&_pre]:p-0`}
        dangerouslySetInnerHTML={{ __html: html }} // nosec: Shiki-generated, not user content
      />
    )
  }

  return (
    <pre style={FILL} className={`${FILL_CLS} p-4 text-[13px]`}>
      <code>{content}</code>
    </pre>
  )
}

// ─── HTML ────────────────────────────────────────────────────────────────────

const HTML_SCROLLBAR_CSS = `<style>*::-webkit-scrollbar{width:6px;height:6px}*::-webkit-scrollbar-track{background:transparent}*::-webkit-scrollbar-thumb{background:rgba(201,168,76,.2);border-radius:3px}*::-webkit-scrollbar-thumb:hover{background:rgba(201,168,76,.4)}*{scrollbar-width:thin;scrollbar-color:rgba(201,168,76,.2) transparent}</style>`
const HTML_ESCAPE_SCRIPT = `<script>window.addEventListener('keydown',function(e){if(e.key==='Escape')window.parent.postMessage({type:'artefact-escape'},'*')})</script>`

function HtmlPreview({ content }: { content: string }) {
  // Inject scrollbar CSS and escape handler into the HTML content
  const enhanced = content.replace('</head>', `${HTML_SCROLLBAR_CSS}${HTML_ESCAPE_SCRIPT}</head>`)
  const srcDoc = enhanced === content ? `${HTML_SCROLLBAR_CSS}${HTML_ESCAPE_SCRIPT}${content}` : enhanced

  return (
    <iframe
      srcDoc={srcDoc}
      sandbox="allow-scripts"
      style={{ width: '100%', height: '100%', border: 'none' }}
      className="bg-white rounded"
      title="HTML preview"
    />
  )
}

// ─── SVG ────────────────────────────────────────────────────────────────────

function utf8ToBase64(input: string): string {
  const bytes = new TextEncoder().encode(input)
  let binary = ''
  for (let i = 0; i < bytes.length; i++) binary += String.fromCharCode(bytes[i])
  return btoa(binary)
}

function SvgPreview({ content }: { content: string }) {
  const dataUri = `data:image/svg+xml;base64,${utf8ToBase64(content)}`

  return (
    <div style={{ ...FILL, display: 'flex', alignItems: 'center', justifyContent: 'center' }} className="p-4">
      <img src={dataUri} alt="SVG preview" className="max-h-full max-w-full object-contain" />
    </div>
  )
}

// ─── JSX ────────────────────────────────────────────────────────────────────

/**
 * Preprocess JSX code for browser execution:
 * - Strip `import` statements (no module system in <script>; React globals are pre-loaded)
 * - Strip `export default` and detect the component name to render
 * - Emit destructured React bindings so hooks like useState work as globals
 */
function preprocessJsx(code: string): { code: string; componentName: string } {
  let processed = code
  let componentName = 'App'

  // Collect named imports from 'react' so we can re-emit them as destructured globals
  const reactNamedImports = new Set<string>()
  const reactImportPattern = /import\s+(?:React\s*,\s*)?\{([^}]+)\}\s+from\s+['"]react['"]\s*;?/g
  let rim
  while ((rim = reactImportPattern.exec(processed)) !== null) {
    rim[1].split(',').map(s => s.trim().split(/\s+as\s+/).pop()!.trim()).forEach(n => {
      if (n) reactNamedImports.add(n)
    })
  }

  // Strip all import statements (react, react-dom, CSS side-effect imports, etc.)
  processed = processed.replace(/^import\s+.*?from\s+['"].*?['"]\s*;?\s*$/gm, '')
  processed = processed.replace(/^import\s+['"].*?['"]\s*;?\s*$/gm, '')

  // Emit destructured React hooks/helpers as top-level const
  if (reactNamedImports.size > 0) {
    const names = [...reactNamedImports].join(', ')
    processed = `const { ${names} } = React;\n${processed}`
  }

  // export default function Name() { ... }
  const funcMatch = processed.match(/export\s+default\s+function\s+(\w+)/)
  if (funcMatch) {
    componentName = funcMatch[1]
    processed = processed.replace(/export\s+default\s+function\s+/, 'function ')
    return { code: processed, componentName }
  }

  // export default class Name { ... }
  const classMatch = processed.match(/export\s+default\s+class\s+(\w+)/)
  if (classMatch) {
    componentName = classMatch[1]
    processed = processed.replace(/export\s+default\s+class\s+/, 'class ')
    return { code: processed, componentName }
  }

  // export default Name (reference to existing variable, typically last line)
  const refMatch = processed.match(/export\s+default\s+(\w+)\s*;?\s*$/)
  if (refMatch) {
    componentName = refMatch[1]
    processed = processed.replace(/export\s+default\s+\w+\s*;?\s*$/, '')
    return { code: processed, componentName }
  }

  // export default () => ... (anonymous arrow)
  if (/export\s+default\s+/.test(processed)) {
    processed = processed.replace(/export\s+default\s+/, 'const _DefaultComponent = ')
    componentName = '_DefaultComponent'
    return { code: processed, componentName }
  }

  return { code: processed, componentName }
}

const JSX_SANDBOX_HTML = (userCode: string, componentName: string) => `<!DOCTYPE html>
<html>
<head>
  <meta charset="UTF-8" />
  <script src="https://unpkg.com/react@18/umd/react.development.js" crossorigin></script>
  <script src="https://unpkg.com/react-dom@18/umd/react-dom.development.js" crossorigin></script>
  <script src="https://unpkg.com/@babel/standalone/babel.min.js"></script>
  <style>
    body { margin: 0; font-family: sans-serif; }
    *::-webkit-scrollbar { width: 6px; height: 6px; }
    *::-webkit-scrollbar-track { background: transparent; }
    *::-webkit-scrollbar-thumb { background: rgba(0,0,0,0.15); border-radius: 3px; }
    *::-webkit-scrollbar-thumb:hover { background: rgba(0,0,0,0.25); }
    * { scrollbar-width: thin; scrollbar-color: rgba(0,0,0,0.15) transparent; }
  </style>
  <script>window.addEventListener('keydown',function(e){if(e.key==='Escape')window.parent.postMessage({type:'artefact-escape'},'*')})</script>
</head>
<body>
  <div id="root"></div>
  <script type="text/babel">
${userCode}

const root = ReactDOM.createRoot(document.getElementById('root'));
try {
  root.render(React.createElement(${componentName}));
} catch(e) {
  root.render(React.createElement('pre', {style:{color:'red',padding:'1em'}}, e.message));
}
  </script>
</body>
</html>`

function JsxPreview({ content }: { content: string }) {
  const { code, componentName } = preprocessJsx(content)
  return (
    <iframe
      srcDoc={JSX_SANDBOX_HTML(code, componentName)}
      sandbox="allow-scripts"
      style={{ width: '100%', height: '100%', border: 'none' }}
      className="bg-white rounded"
      title="JSX preview"
    />
  )
}

// ─── Mermaid ────────────────────────────────────────────────────────────────

// Cache the dynamic import promise at module level so we don't re-resolve on every content change
let mermaidPromise: Promise<typeof import('mermaid')> | null = null
function loadMermaid(): Promise<typeof import('mermaid')> {
  if (!mermaidPromise) mermaidPromise = import('mermaid')
  return mermaidPromise
}

function MermaidPreview({ content }: { content: string }) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!containerRef.current) return

    let cancelled = false

    loadMermaid().then((mod) => {
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
      <div style={{ ...FILL, display: 'flex', alignItems: 'center', justifyContent: 'center' }} className="p-4">
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
      style={{ ...FILL, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
      className="p-4 [&_svg]:max-h-full [&_svg]:max-w-full"
    />
  )
}

// ─── Main switcher ───────────────────────────────────────────────────────────

interface ArtefactPreviewProps {
  content: string
  type: ArtefactType
  language: string | null
  /** User override — when set, skips language-based detection and renders this type directly. */
  typeOverride?: ArtefactType | null
}

/**
 * Detect which preview renderer to use.
 *
 * LLMs inconsistently set the artefact type when creating code artefacts — a
 * single-page HTML website may come through as type='code' + language='html'
 * instead of type='html'. Without this normalisation the preview shows the raw
 * source instead of rendering the page. The same applies to JSX components,
 * markdown documents, SVG, and mermaid diagrams. The `language` hint is
 * matched case-insensitively.
 */
export function detectPreviewType(type: ArtefactType, language: string | null): ArtefactType {
  if (type !== 'code') return type
  const lang = language?.toLowerCase().trim()
  if (!lang) return type
  if (lang === 'html' || lang === 'htm') return 'html'
  if (lang === 'jsx' || lang === 'tsx') return 'jsx'
  if (lang === 'md' || lang === 'markdown') return 'markdown'
  if (lang === 'svg') return 'svg'
  if (lang === 'mermaid') return 'mermaid'
  return type
}

export function ArtefactPreview({ content, type, language, typeOverride }: ArtefactPreviewProps) {
  const highlighter = useHighlighter()

  const effectiveType = typeOverride ?? detectPreviewType(type, language)

  switch (effectiveType) {
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
