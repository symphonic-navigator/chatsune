import { useEffect, useState } from 'react'
import { createHighlighter, type Highlighter } from 'shiki'

let highlighterPromise: Promise<Highlighter> | null = null
let cachedHighlighter: Highlighter | null = null

function getHighlighter(): Promise<Highlighter> {
  if (cachedHighlighter) return Promise.resolve(cachedHighlighter)
  if (!highlighterPromise) {
    highlighterPromise = createHighlighter({
      themes: ['github-dark-dimmed'],
      langs: [
        'javascript', 'typescript', 'python', 'bash', 'json', 'html', 'css',
        'markdown', 'yaml', 'toml', 'sql', 'rust', 'go', 'java', 'csharp',
        'xml', 'dockerfile', 'shell',
      ],
    }).then((h) => {
      cachedHighlighter = h
      return h
    })
  }
  return highlighterPromise
}

export function useHighlighter() {
  const [highlighter, setHighlighter] = useState<Highlighter | null>(cachedHighlighter)

  useEffect(() => {
    if (cachedHighlighter) {
      setHighlighter(cachedHighlighter)
      return
    }
    let cancelled = false
    getHighlighter().then((h) => {
      if (!cancelled) setHighlighter(h)
    })
    return () => { cancelled = true }
  }, [])

  return highlighter
}
