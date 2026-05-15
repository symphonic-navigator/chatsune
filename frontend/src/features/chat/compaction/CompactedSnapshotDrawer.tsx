import { useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import type { CompactionCheckpoint } from '../../../core/api/chat'

interface Props {
  /** ``null`` hides the drawer; setting a checkpoint opens it. */
  checkpoint: CompactionCheckpoint | null
  onClose: () => void
}

function formatTime(iso: string): string {
  const d = new Date(iso)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

/**
 * Read-only snapshot view for a compaction checkpoint. Renders the
 * stored ``summary_markdown`` through ``react-markdown`` (already a
 * project dependency — also used by the deletion-report sheet and the
 * artefact preview) with prose styling that matches the chat's
 * vocabulary.
 *
 * Layout (Task 10.4): right-side slide-over, 480 px wide, full height,
 * anchored to the viewport's right edge. The mobile full-screen variant
 * is added in a follow-up task (10.5).
 *
 * Escape key dismisses; the close button does the same. See
 * ``devdocs/specs/2026-05-15-compact-and-continue-design.md`` §5.4.
 */
export function CompactedSnapshotDrawer({ checkpoint, onClose }: Props) {
  useEffect(() => {
    if (!checkpoint) return
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', handleKey)
    return () => window.removeEventListener('keydown', handleKey)
  }, [checkpoint, onClose])

  if (!checkpoint) return null

  // ``model_unique_id`` has the shape ``<connection_id>:<model_slug>``;
  // the slug after the last colon is the user-facing model label.
  const modelLabel =
    checkpoint.model_unique_id.split(':').pop() ?? checkpoint.model_unique_id

  return (
    <aside
      role="dialog"
      aria-label="Compaction snapshot"
      className="fixed top-0 right-0 z-50 flex h-full w-[480px] max-w-full flex-col border-l border-white/10 bg-[#0b0a08] shadow-[0_8px_24px_rgba(0,0,0,0.5)]"
    >
      <header className="flex items-start justify-between border-b border-white/10 p-4">
        <div className="min-w-0 pr-4">
          <h3 className="font-mono text-[12px] font-semibold text-white/85 truncate">
            <span aria-hidden>{'✨ '}</span>
            Compact snapshot · {formatTime(checkpoint.created_at)} · {modelLabel}
          </h3>
          <p className="mt-1 font-mono text-[11px] text-white/55">
            Original {checkpoint.tokens_before.toLocaleString()} tokens → Briefing{' '}
            {checkpoint.tokens_after.toLocaleString()} tokens
          </p>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close drawer"
          className="rounded p-1 text-lg leading-none text-white/55 hover:bg-white/6 hover:text-white/85 transition-colors"
        >
          ×
        </button>
      </header>
      <div className="flex-1 overflow-y-auto p-4 text-[13px] leading-relaxed text-white/80">
        <ReactMarkdown
          components={{
            h1: ({ children }) => (
              <h1 className="text-[15px] font-semibold text-white/90 mt-0 mb-3">{children}</h1>
            ),
            h2: ({ children }) => (
              <h2 className="text-[14px] font-semibold text-white/85 mt-5 mb-2">{children}</h2>
            ),
            h3: ({ children }) => (
              <h3 className="text-[13px] font-semibold text-white/80 mt-4 mb-2">{children}</h3>
            ),
            p: ({ children }) => <p className="my-2">{children}</p>,
            ul: ({ children }) => (
              <ul className="list-disc list-inside space-y-1 text-white/80 my-2">{children}</ul>
            ),
            ol: ({ children }) => (
              <ol className="list-decimal list-inside space-y-1 text-white/80 my-2">{children}</ol>
            ),
            code: ({ children }) => (
              <code className="rounded bg-white/8 px-1 py-0.5 font-mono text-[12px] text-white/85">
                {children}
              </code>
            ),
            pre: ({ children }) => (
              <pre className="my-2 overflow-x-auto rounded border border-white/10 bg-black/30 p-3 font-mono text-[12px] text-white/80">
                {children}
              </pre>
            ),
          }}
        >
          {checkpoint.summary_markdown}
        </ReactMarkdown>
      </div>
    </aside>
  )
}
