import { useEffect, useId, useMemo, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import { createMarkdownComponents, remarkPlugins, rehypePlugins, preprocessMath } from '../../../features/chat/markdownComponents'
import { useHighlighter } from '../../../features/chat/useMarkdown'
import { TriggerPhraseEditor } from '../../../features/knowledge/TriggerPhraseEditor'
import { RefreshFrequencySelect, type RefreshFrequency } from '../../../features/knowledge/RefreshFrequencySelect'

interface DocumentEditorModalProps {
  libraryId: string
  libraryDefaultRefresh: RefreshFrequency
  initial?: {
    title: string
    content: string
    media_type: 'text/markdown' | 'text/plain'
    trigger_phrases?: string[]
    refresh?: RefreshFrequency | null
  }
  onSave: (data: {
    title: string
    content: string
    media_type: 'text/markdown' | 'text/plain'
    trigger_phrases: string[]
    refresh: RefreshFrequency | null
  }) => Promise<void>
  /**
   * Optional autosave callback for trigger phrases — fires (debounced) after
   * the user adds or removes a phrase. Only wired in edit mode; in create mode
   * the document does not exist yet so phrases live with the rest of the
   * payload until the explicit Save click.
   */
  onAutosaveTriggerPhrases?: (phrases: string[]) => Promise<void>
  onDelete?: () => Promise<void>
  onClose: () => void
}

export function DocumentEditorModal({ libraryId: _libraryId, libraryDefaultRefresh, initial, onSave, onAutosaveTriggerPhrases, onDelete, onClose }: DocumentEditorModalProps) {
  const highlighter = useHighlighter()
  const markdownComponents = useMemo(() => createMarkdownComponents(highlighter), [highlighter])
  const [title, setTitle] = useState(initial?.title ?? '')
  const [content, setContent] = useState(initial?.content ?? '')
  const [mediaType, setMediaType] = useState<'text/markdown' | 'text/plain'>(initial?.media_type ?? 'text/markdown')
  const [triggerPhrases, setTriggerPhrases] = useState<string[]>(initial?.trigger_phrases ?? [])
  const [refresh, setRefresh] = useState<RefreshFrequency | null>(initial?.refresh ?? null)
  const [preview, setPreview] = useState(false)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [confirmDiscard, setConfirmDiscard] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const titleId = useId()
  const editorId = useId()
  const titleRef = useRef<HTMLInputElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const deleteTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const isDirty = useRef(false)
  const isEdit = initial !== undefined
  // Tracks the last successfully persisted trigger phrases so handleClose
  // does not flag autosaved changes as "unsaved".
  const persistedPhrasesRef = useRef<string[]>(initial?.trigger_phrases ?? [])
  const autosaveTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const autosaveLastSentRef = useRef<string[]>(initial?.trigger_phrases ?? [])

  useEffect(() => {
    titleRef.current?.focus()
    return () => {
      if (deleteTimerRef.current) clearTimeout(deleteTimerRef.current)
      if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current)
    }
  }, [])

  // Track changes after initial render
  useEffect(() => {
    isDirty.current = true
  }, [title, content, mediaType, triggerPhrases, refresh])

  // Reset dirty flag once on mount
  useEffect(() => {
    isDirty.current = false
  }, [])

  // Debounced autosave for trigger phrases — fires after the user adds or
  // removes a phrase. Skips initial mount (initial render already matches
  // the server state) and only runs in edit mode (a fresh document has no
  // ID to PATCH against).
  useEffect(() => {
    if (!onAutosaveTriggerPhrases) return
    const last = autosaveLastSentRef.current
    const unchanged =
      triggerPhrases.length === last.length &&
      triggerPhrases.every((p, i) => p === last[i])
    if (unchanged) return
    if (autosaveTimerRef.current) clearTimeout(autosaveTimerRef.current)
    const snapshot = triggerPhrases.slice()
    autosaveTimerRef.current = setTimeout(() => {
      autosaveLastSentRef.current = snapshot
      onAutosaveTriggerPhrases(snapshot)
        .then(() => {
          persistedPhrasesRef.current = snapshot
        })
        .catch(() => {
          // Allow a retry on the next change by un-marking this snapshot
          // as the last sent value.
          autosaveLastSentRef.current = persistedPhrasesRef.current
        })
    }, 500)
  }, [triggerPhrases, onAutosaveTriggerPhrases])

  function handleClose() {
    const referencePhrases = persistedPhrasesRef.current
    const phrasesChanged =
      triggerPhrases.length !== referencePhrases.length ||
      triggerPhrases.some((p, i) => p !== referencePhrases[i])
    if (
      isDirty.current &&
      (
        title !== (initial?.title ?? '') ||
        content !== (initial?.content ?? '') ||
        phrasesChanged ||
        refresh !== (initial?.refresh ?? null)
      )
    ) {
      if (!confirmDiscard) {
        setConfirmDiscard(true)
        return
      }
    }
    onClose()
  }

  async function handleSave() {
    if (!title.trim()) return
    setSaving(true)
    setError(null)
    try {
      await onSave({ title: title.trim(), content, media_type: mediaType, trigger_phrases: triggerPhrases, refresh })
      isDirty.current = false
      onClose()
    } catch {
      setError('Failed to save document')
      setSaving(false)
    }
  }

  function handleDeleteClick() {
    if (!onDelete) return
    if (confirmDelete) {
      setDeleting(true)
      onDelete()
        .then(() => {
          isDirty.current = false
          onClose()
        })
        .catch(() => {
          setError('Failed to delete document')
          setDeleting(false)
          setConfirmDelete(false)
        })
    } else {
      setConfirmDelete(true)
      deleteTimerRef.current = setTimeout(() => setConfirmDelete(false), 3000)
    }
  }

  function handleFileUpload(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    if (!file) return
    const reader = new FileReader()
    reader.onload = (ev) => {
      const text = ev.target?.result
      if (typeof text === 'string') {
        setContent(text)
        if (file.name.endsWith('.md') || file.name.endsWith('.markdown')) {
          setMediaType('text/markdown')
        } else {
          setMediaType('text/plain')
        }
        if (!title) setTitle(file.name.replace(/\.(md|txt|markdown)$/, ''))
      }
    }
    reader.readAsText(file)
    // Reset so same file can be re-uploaded
    e.target.value = ''
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') handleClose()
  }

  const isMarkdown = mediaType === 'text/markdown'

  return (
    <div
      className="fixed inset-0 z-50 flex flex-col overflow-y-auto bg-black/60 lg:items-center lg:justify-center lg:overflow-hidden lg:px-[5vw] lg:py-[5vh]"
      onClick={(e) => { if (e.target === e.currentTarget) handleClose() }}
      onKeyDown={handleKeyDown}
    >
      <div role="dialog" aria-modal="true" aria-label={isEdit ? 'Edit document' : 'New document'} className="flex min-h-full w-full flex-col bg-elevated shadow-2xl lg:h-full lg:min-h-0 lg:max-w-none lg:rounded-xl lg:border lg:border-white/8">
        {/* Header */}
        <div
          className="flex items-center gap-3 border-b border-white/6 px-5 py-3"
          style={{ paddingTop: 'max(0.75rem, env(safe-area-inset-top))' }}
        >
          <div className="flex-1">
            <label htmlFor={titleId} className="sr-only">Document title</label>
            <input
              id={titleId}
              ref={titleRef}
              type="text"
              value={title}
              onChange={(e) => { setTitle(e.target.value.slice(0, 500)); if (confirmDiscard) setConfirmDiscard(false) }}
              maxLength={500}
              placeholder="Document title..."
              className="w-full bg-transparent text-[14px] font-mono text-white/80 placeholder-white/20 outline-none"
            />
          </div>
          <div className="flex items-center gap-1.5">
            {/* Media type toggle */}
            <button
              type="button"
              onClick={() => setMediaType(isMarkdown ? 'text/plain' : 'text/markdown')}
              className={[
                'rounded border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider transition-colors cursor-pointer',
                isMarkdown
                  ? 'border-gold/30 text-gold hover:bg-gold/10'
                  : 'border-white/8 text-white/40 hover:border-white/15 hover:text-white/60',
              ].join(' ')}
              title={`Switch to ${isMarkdown ? 'plain text' : 'markdown'}`}
            >
              {isMarkdown ? 'MD' : 'TXT'}
            </button>

            {/* Preview toggle (only for markdown) */}
            {isMarkdown && (
              <button
                type="button"
                onClick={() => setPreview(!preview)}
                className={[
                  'rounded border px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider transition-colors cursor-pointer',
                  preview
                    ? 'border-gold/30 bg-gold/10 text-gold'
                    : 'border-white/8 text-white/40 hover:border-white/15 hover:text-white/60',
                ].join(' ')}
              >
                Preview
              </button>
            )}

            {/* File upload */}
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              className="rounded border border-white/8 px-2 py-0.5 text-[10px] font-mono uppercase tracking-wider text-white/40 transition-colors hover:border-white/15 hover:text-white/60 cursor-pointer"
              title="Upload .md, .txt, or .markdown file"
            >
              Upload
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".md,.txt,.markdown"
              onChange={handleFileUpload}
              className="hidden"
            />
          </div>
        </div>

        {/* Editor area */}
        <div className="flex flex-1 lg:min-h-0">
          {/* Editor */}
          <label htmlFor={editorId} className="sr-only">Document content</label>
          <textarea
            id={editorId}
            value={content}
            onChange={(e) => { setContent(e.target.value); if (confirmDiscard) setConfirmDiscard(false) }}
            aria-label="Document content"
            placeholder={isMarkdown ? '# Start writing in Markdown...' : 'Start writing...'}
            className={[
              'min-h-[60vh] resize-none bg-transparent px-5 py-4 text-[13px] font-mono text-white/75 placeholder-white/15 outline-none lg:min-h-0',
              preview ? 'w-1/2 border-r border-white/6' : 'w-full',
            ].join(' ')}
          />

          {/* Preview */}
          {preview && isMarkdown && (
            <div className="markdown-preview w-1/2 overflow-y-auto px-5 py-4">
              {content ? (
                <ReactMarkdown remarkPlugins={remarkPlugins} rehypePlugins={rehypePlugins} components={markdownComponents}>
                  {preprocessMath(content)}
                </ReactMarkdown>
              ) : (
                <p className="text-white/20 font-mono text-[12px]">Nothing to preview</p>
              )}
            </div>
          )}
        </div>

        {/* PTI controls */}
        <div className="flex flex-col gap-3 border-t border-white/6 px-5 py-3 lg:max-h-48 lg:overflow-y-auto">
          <div className="space-y-1">
            <label className="text-[11px] font-mono uppercase tracking-wider text-white/60">
              Trigger phrases
            </label>
            <TriggerPhraseEditor value={triggerPhrases} onChange={setTriggerPhrases} />
          </div>
          <RefreshFrequencySelect
            label="Refresh frequency"
            value={refresh}
            onChange={setRefresh}
            inheritFrom={libraryDefaultRefresh}
          />
        </div>

        {/* Footer */}
        <div
          className="flex items-center justify-between border-t border-white/6 px-5 py-3"
          style={{ paddingBottom: 'max(0.75rem, env(safe-area-inset-bottom))' }}
        >
          <div>
            {error && (
              <p className="text-[11px] text-red-400 font-mono">{error}</p>
            )}
            {isEdit && onDelete && (
              <button
                type="button"
                onClick={handleDeleteClick}
                disabled={deleting}
                className={[
                  'rounded border px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors',
                  confirmDelete
                    ? 'border-red-400/40 bg-red-400/10 text-red-400 hover:bg-red-400/15 cursor-pointer'
                    : 'border-white/8 text-white/30 hover:border-red-400/30 hover:text-red-400 cursor-pointer',
                  deleting ? 'cursor-not-allowed opacity-30' : '',
                ].join(' ')}
              >
                {deleting ? 'Deleting...' : confirmDelete ? 'Sure?' : 'Delete'}
              </button>
            )}
          </div>
          <div className="flex gap-2 items-center">
            {confirmDiscard && (
              <span role="status" aria-live="polite" className="text-[10px] font-mono uppercase tracking-wider text-red-400">
                Unsaved changes — click again to discard
              </span>
            )}
            <button
              type="button"
              onClick={handleClose}
              aria-label={confirmDiscard ? 'Discard unsaved changes' : 'Cancel and close editor'}
              disabled={saving || deleting}
              className={[
                'rounded border px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider transition-colors cursor-pointer',
                confirmDiscard
                  ? 'border-red-400/40 bg-red-400/10 text-red-400 hover:bg-red-400/15'
                  : 'border-white/8 text-white/60 hover:border-white/15 hover:text-white/80',
              ].join(' ')}
            >
              {confirmDiscard ? 'Discard?' : 'Cancel'}
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={!title.trim() || saving || deleting}
              className={[
                'rounded border border-gold/30 px-2.5 py-1 text-[10px] font-mono uppercase tracking-wider text-gold transition-colors',
                !title.trim() || saving || deleting
                  ? 'cursor-not-allowed opacity-30'
                  : 'cursor-pointer hover:bg-gold/10 hover:border-gold/40',
              ].join(' ')}
            >
              {saving ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}
