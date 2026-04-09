import { useCallback, useEffect, useRef, useState } from 'react'
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
  const copyTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  useEffect(() => () => {
    if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
  }, [])

  useEffect(() => {
    setMode('preview')
    setEditContent(artefact?.content ?? '')
  }, [artefact?.handle, artefact?.version])

  useEffect(() => {
    function handleKey(e: KeyboardEvent) {
      if (e.key === 'Escape') closeOverlay()
    }
    // Escape from iframe previews (they postMessage since keydown doesn't cross iframe boundary)
    function handleMessage(e: MessageEvent) {
      if (e.data?.type === 'artefact-escape') closeOverlay()
    }
    document.addEventListener('keydown', handleKey)
    window.addEventListener('message', handleMessage)
    return () => {
      document.removeEventListener('keydown', handleKey)
      window.removeEventListener('message', handleMessage)
    }
  }, [closeOverlay])

  const handleCopy = useCallback(() => {
    if (!artefact) return
    navigator.clipboard.writeText(artefact.content).then(() => {
      setCopied(true)
      if (copyTimeoutRef.current) clearTimeout(copyTimeoutRef.current)
      copyTimeoutRef.current = setTimeout(() => setCopied(false), 1500)
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
    <>
      {/* Backdrop — same pattern as PersonaOverlay / UserModal. On mobile the
          overlay is full-screen so the backdrop is effectively hidden behind
          the panel, but we keep it for consistency and future edge insets. */}
      <div className="fixed inset-0 bg-black/50 z-10" onClick={closeOverlay} />

      {/* Panel — full-screen on mobile, absolute-inset-4 card on desktop. */}
      <div
        className="fixed inset-0 lg:absolute lg:inset-4 z-20 flex flex-col bg-elevated border border-white/10 rounded-none lg:rounded-xl shadow-2xl overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Toolbar */}
        <div className="flex shrink-0 items-center gap-2 border-b border-white/8 px-3 py-2">
          <div className="flex min-w-0 flex-1 items-center gap-2">
            <span className="truncate text-[13px] text-white/80" title={artefact?.title ?? ''}>
              {artefact?.title ?? '...'}
            </span>
            {artefact && (
              <span
                className="shrink-0 rounded px-1.5 py-0.5 text-[10px] font-mono uppercase tracking-wider"
                style={{ background: `rgba(${rgb},0.12)`, color: `rgb(${rgb})`, border: `1px solid rgba(${rgb},0.25)` }}
              >
                {artefact.type}
              </span>
            )}
            {artefact?.language && (
              <span className="shrink-0 text-[10px] font-mono text-white/30">{artefact.language}</span>
            )}
          </div>
          <div className="flex items-center gap-1 overflow-x-auto">
            <button type="button" onClick={() => setMode('preview')}
              className={`${BTN_BASE} ${mode === 'preview' ? BTN_ACTIVE : BTN_INACTIVE}`}>Preview</button>
            <button type="button" onClick={() => { setMode('edit'); setEditContent(artefact?.content ?? '') }}
              className={`${BTN_BASE} ${mode === 'edit' ? BTN_ACTIVE : BTN_INACTIVE}`}>Edit</button>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <button type="button" onClick={handleCopy} className={BTN_ICON}>{copied ? 'Copied' : 'Copy'}</button>
            <button type="button" onClick={handleDownload} className={BTN_ICON}>Download</button>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <button type="button" onClick={handleUndo} disabled={undoDisabled}
              className={`${BTN_ICON} disabled:opacity-20 disabled:cursor-not-allowed`}>Undo</button>
            <button type="button" onClick={handleRedo} disabled={redoDisabled}
              className={`${BTN_ICON} disabled:opacity-20 disabled:cursor-not-allowed`}>Redo</button>
            <span className="mx-1 h-4 w-px bg-white/10" />
            <button type="button" onClick={closeOverlay} className={BTN_ICON}>&#10005;</button>
          </div>
        </div>

        {/* Content area */}
        <div className="relative min-h-0 flex-1">
          {loading && (
            <div className="absolute inset-0 flex items-center justify-center">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-white/20 border-t-white/50" />
            </div>
          )}

          {!loading && artefact && mode === 'preview' && (
            <ArtefactPreview content={artefact.content} type={artefact.type} language={artefact.language} />
          )}

          {!loading && artefact && mode === 'edit' && (
            <div className="flex h-full flex-col">
              <textarea
                className="min-h-0 flex-1 resize-none bg-transparent p-4 font-mono text-[12px] text-white/80 outline-none"
                value={editContent}
                onChange={(e) => setEditContent(e.target.value)}
                spellCheck={false}
              />
              {isDirty && (
                <div className="flex shrink-0 items-center justify-end gap-2 border-t border-white/8 px-3 py-2">
                  <button type="button" onClick={() => setEditContent(artefact.content)}
                    className={`${BTN_BASE} ${BTN_INACTIVE}`}>Discard</button>
                  <button type="button" onClick={handleSave} disabled={saving}
                    className={`${BTN_BASE} ${BTN_ACTIVE} disabled:opacity-50`}>{saving ? 'Saving...' : 'Save'}</button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  )
}
