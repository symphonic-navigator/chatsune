import { useCallback, useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { useArtefactStore } from '../../core/store/artefactStore'
import { artefactApi } from '../../core/api/artefact'
import { ArtefactPreview } from './ArtefactPreview'

const TYPE_COLOURS: Record<string, string> = {
  markdown: '180,180,220',
  code: '137,180,250',
  html: '250,170,130',
  svg: '170,220,170',
  jsx: '140,180,250',
  mermaid: '200,170,250',
}

const BTN_BASE =
  'rounded border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider cursor-pointer transition-colors'
const BTN_ACTIVE = 'border-gold/30 bg-gold/10 text-gold'
const BTN_INACTIVE = 'border-white/8 text-white/40 hover:text-white/60'
const BTN_ICON = `${BTN_BASE} ${BTN_INACTIVE}`

function getExtension(type: string, language: string | null): string {
  if (type === 'markdown') return '.md'
  if (type === 'code' && language) return `.${language}`
  if (type === 'code') return '.txt'
  return `.${type}`
}

export function ArtefactOverlay() {
  const { sessionId } = useParams<{ sessionId?: string }>()
  const artefact = useArtefactStore((s) => s.activeArtefact)
  const loading = useArtefactStore((s) => s.activeArtefactLoading)
  const closeOverlay = useArtefactStore((s) => s.closeOverlay)
  const setActiveArtefact = useArtefactStore((s) => s.setActiveArtefact)

  const [mode, setMode] = useState<'preview' | 'edit'>('preview')
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)
  const [copied, setCopied] = useState(false)

  // Reset mode and edit content when the artefact handle/version changes
  useEffect(() => {
    setMode('preview')
    setEditContent(artefact?.content ?? '')
  }, [artefact?.handle, artefact?.version])

  // Close on Escape
  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') {
        closeOverlay()
      }
    }
    document.addEventListener('keydown', handleKey)
    return () => document.removeEventListener('keydown', handleKey)
  }, [closeOverlay])

  const handleCopy = useCallback(() => {
    if (!artefact) return
    navigator.clipboard.writeText(artefact.content).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }, [artefact])

  const handleDownload = useCallback(() => {
    if (!artefact) return
    const ext = getExtension(artefact.type, artefact.language)
    const blob = new Blob([artefact.content], { type: 'text/plain' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `${artefact.handle}${ext}`
    a.click()
    URL.revokeObjectURL(url)
  }, [artefact])

  const handleSave = useCallback(async () => {
    if (!artefact || !sessionId) return
    setSaving(true)
    try {
      const updated = await artefactApi.patch(sessionId, artefact.id, { content: editContent })
      setActiveArtefact(updated)
    } finally {
      setSaving(false)
    }
  }, [artefact, sessionId, editContent, setActiveArtefact])

  const handleUndo = useCallback(async () => {
    if (!artefact || !sessionId) return
    const updated = await artefactApi.undo(sessionId, artefact.id)
    setActiveArtefact(updated)
  }, [artefact, sessionId, setActiveArtefact])

  const handleRedo = useCallback(async () => {
    if (!artefact || !sessionId) return
    const updated = await artefactApi.redo(sessionId, artefact.id)
    setActiveArtefact(updated)
  }, [artefact, sessionId, setActiveArtefact])

  if (!artefact && !loading) return null

  const rgb = artefact ? (TYPE_COLOURS[artefact.type] ?? '180,180,180') : '180,180,180'
  const isDirty = artefact ? editContent !== artefact.content : false
  const undoDisabled = !artefact || artefact.version <= 1
  const redoDisabled = !artefact || artefact.version >= artefact.max_version

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50" onClick={closeOverlay}>
      <div
        className="overflow-hidden rounded-lg border border-white/10 bg-elevated shadow-2xl"
        style={{
          width: 'calc(100vw - 120px)',
          height: 'calc(100vh - 80px)',
          maxWidth: '1200px',
          display: 'grid',
          gridTemplateRows: 'auto 1fr',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Toolbar */}
        <div className="flex items-center gap-2 border-b border-white/8 px-3 py-2">
          {/* Left: title + badges */}
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-[13px] text-white/80" title={artefact?.title ?? ''}>
              {artefact?.title ?? '…'}
            </span>
            {artefact && (
              <span
                className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider"
                style={{
                  background: `rgba(${rgb},0.12)`,
                  color: `rgb(${rgb})`,
                  border: `1px solid rgba(${rgb},0.25)`,
                }}
              >
                {artefact.type}
              </span>
            )}
            {artefact?.language && (
              <span className="shrink-0 text-[10px] font-mono text-white/30">
                {artefact.language}
              </span>
            )}
          </div>

          {/* Right: action buttons */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => { setMode('preview') }}
              className={`${BTN_BASE} ${mode === 'preview' ? BTN_ACTIVE : BTN_INACTIVE}`}
            >
              Preview
            </button>
            <button
              type="button"
              onClick={() => { setMode('edit'); setEditContent(artefact?.content ?? '') }}
              className={`${BTN_BASE} ${mode === 'edit' ? BTN_ACTIVE : BTN_INACTIVE}`}
            >
              Edit
            </button>

            <span className="mx-1 h-4 w-px bg-white/10" />

            <button
              type="button"
              onClick={handleCopy}
              className={BTN_ICON}
              title="Copy to clipboard"
            >
              {copied ? 'Copied' : 'Copy'}
            </button>
            <button
              type="button"
              onClick={handleDownload}
              className={BTN_ICON}
              title="Download file"
            >
              Download
            </button>

            <span className="mx-1 h-4 w-px bg-white/10" />

            <button
              type="button"
              onClick={handleUndo}
              disabled={undoDisabled}
              className={`${BTN_ICON} disabled:opacity-20 disabled:cursor-not-allowed`}
              title="Undo"
            >
              Undo
            </button>
            <button
              type="button"
              onClick={handleRedo}
              disabled={redoDisabled}
              className={`${BTN_ICON} disabled:opacity-20 disabled:cursor-not-allowed`}
              title="Redo"
            >
              Redo
            </button>

            <span className="mx-1 h-4 w-px bg-white/10" />

            <button
              type="button"
              onClick={closeOverlay}
              className={BTN_ICON}
              title="Close (Escape)"
            >
              ✕
            </button>
          </div>
        </div>

        {/* Content area — second grid row (1fr), children fill automatically */}
        <div style={{ overflow: 'hidden', position: 'relative' }}>
          {loading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/50" />
            </div>
          )}

          {!loading && artefact && mode === 'preview' && (
            <ArtefactPreview
              content={artefact.content}
              type={artefact.type}
              language={artefact.language}
            />
          )}

          {!loading && artefact && mode === 'edit' && (
            <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
              <textarea
                className="resize-none bg-transparent p-4 font-mono text-[12px] text-white/80 outline-none placeholder:text-white/20"
                style={{ flex: '1 1 0%', minHeight: 0 }}
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                spellCheck={false}
              />
              {isDirty && (
                <div className="flex items-center justify-end gap-2 border-t border-white/8 px-3 py-2">
                  <button
                    type="button"
                    onClick={() => setEditContent(artefact.content)}
                    className={`${BTN_BASE} ${BTN_INACTIVE}`}
                  >
                    Discard
                  </button>
                  <button
                    type="button"
                    onClick={handleSave}
                    disabled={saving}
                    className={`${BTN_BASE} ${BTN_ACTIVE} disabled:opacity-50`}
                  >
                    {saving ? 'Saving…' : 'Save'}
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
