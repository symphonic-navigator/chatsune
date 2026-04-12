import { useEffect, useRef, useState } from 'react'
import { useMemoryStore } from '../../core/store/memoryStore'
import { memoryApi } from '../../core/api/memory'
import type { MemoryBodyDto, MemoryBodyVersionDto } from '../../core/api/memory'

const TOKEN_LIMIT = 3000

interface Props {
  personaId: string
}

export default function MemoryBodySection({ personaId }: Props) {
  const isDreaming = useMemoryStore((s) => s.isDreaming[personaId] ?? false)
  const setMemoryBody = useMemoryStore((s) => s.setMemoryBody)
  const setBodyVersions = useMemoryStore((s) => s.setBodyVersions)

  const [body, setBody] = useState<MemoryBodyDto | null>(null)
  const [versions, setVersions] = useState<MemoryBodyVersionDto[]>([])
  const [viewingVersion, setViewingVersion] = useState<MemoryBodyDto | null>(null)
  const [loadingVersion, setLoadingVersion] = useState<number | null>(null)
  const [editing, setEditing] = useState(false)
  const [editContent, setEditContent] = useState('')
  const [saving, setSaving] = useState(false)

  const loadBodyAndVersions = async (cancelled: { value: boolean }) => {
    try {
      const [bodyResult, versionsResult] = await Promise.all([
        memoryApi.getMemoryBody(personaId),
        memoryApi.listBodyVersions(personaId),
      ])
      if (!cancelled.value) {
        setBody(bodyResult)
        setMemoryBody(personaId, bodyResult)
        setVersions(versionsResult)
        setBodyVersions(personaId, versionsResult)
      }
    } catch {
      // body may not exist yet — treat as empty
    }
  }

  // Shared cancel flag — both effects must invalidate any in-flight load when they re-run or unmount
  const cancelRef = useRef<{ value: boolean }>({ value: false })

  useEffect(() => {
    cancelRef.current = { value: false }
    const cancelled = cancelRef.current
    loadBodyAndVersions(cancelled)
    return () => { cancelled.value = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaId, setMemoryBody, setBodyVersions])

  const prevIsDreaming = useRef(isDreaming)
  useEffect(() => {
    if (prevIsDreaming.current && !isDreaming) {
      // Reuse the shared cancel flag so the previous load (if still running) is cancelled
      cancelRef.current.value = true
      cancelRef.current = { value: false }
      loadBodyAndVersions(cancelRef.current)
    }
    prevIsDreaming.current = isDreaming
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDreaming])

  const handleLoadVersion = async (version: number) => {
    if (loadingVersion !== null) return
    if (body && version === body.version) {
      setViewingVersion(null)
      return
    }
    setLoadingVersion(version)
    try {
      const result = await memoryApi.getBodyVersion(personaId, version)
      setViewingVersion(result)
    } finally {
      setLoadingVersion(null)
    }
  }

  const [rollbackBusy, setRollbackBusy] = useState(false)

  const handleRollback = async () => {
    if (!viewingVersion || rollbackBusy) return
    setRollbackBusy(true)
    try {
      await memoryApi.rollbackBody(personaId, viewingVersion.version)
      setViewingVersion(null)
    } finally {
      setRollbackBusy(false)
    }
  }

  const handleStartEdit = () => {
    if (!body) return
    setEditContent(body.content)
    setEditing(true)
  }

  const handleSaveEdit = async () => {
    if (saving) return
    setSaving(true)
    try {
      await memoryApi.updateBody(personaId, editContent)
      setEditing(false)
      // Reload body and versions to reflect new version
      cancelRef.current.value = true
      cancelRef.current = { value: false }
      loadBodyAndVersions(cancelRef.current)
    } finally {
      setSaving(false)
    }
  }

  const handleCancelEdit = () => {
    setEditing(false)
    setEditContent('')
  }

  const [deleteBusy, setDeleteBusy] = useState(false)

  const handleDeleteVersion = async () => {
    if (!viewingVersion || deleteBusy) return
    setDeleteBusy(true)
    try {
      await memoryApi.deleteBodyVersion(personaId, viewingVersion.version)
      setViewingVersion(null)
      // Reload versions
      cancelRef.current.value = true
      cancelRef.current = { value: false }
      loadBodyAndVersions(cancelRef.current)
    } finally {
      setDeleteBusy(false)
    }
  }

  const displayed = viewingVersion ?? body
  const isViewingOld = viewingVersion !== null && body !== null && viewingVersion.version !== body.version

  return (
    <div className="rounded-lg border border-white/5 bg-surface overflow-hidden">
      <div className="flex items-center gap-3 px-4 py-3 border-b border-white/5">
        <span className="text-xs text-white/60 font-medium">Memory Body</span>
        {displayed && (
          <span className="text-[11px] text-white/30">
            {displayed.token_count} / {TOKEN_LIMIT} tokens
          </span>
        )}
        {body && !editing && !isViewingOld && !isDreaming && (
          <button
            onClick={handleStartEdit}
            className="ml-auto px-2.5 py-1 rounded text-[11px] text-white/40 hover:text-white/60 hover:bg-white/5 transition-colors"
          >
            Edit
          </button>
        )}
        {isDreaming && (
          <span className="flex items-center gap-1.5 text-[11px] text-purple-400">
            <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
            </svg>
            Dreaming...
          </span>
        )}
      </div>

      <div className="p-4 space-y-4">
        {isViewingOld && (
          <div className="flex items-center gap-3 px-3 py-2 rounded bg-amber-500/5 border border-amber-500/10">
            <span className="text-[11px] text-amber-400">
              Viewing v{viewingVersion.version} — not the current version
            </span>
            <div className="flex gap-2 ml-auto">
              <button
                onClick={handleRollback}
                disabled={rollbackBusy}
                className="px-2.5 py-1 rounded text-[11px] bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
              >
                Rollback to this version
              </button>
              <button
                onClick={handleDeleteVersion}
                disabled={deleteBusy}
                className="px-2.5 py-1 rounded text-[11px] bg-red-500/10 text-red-400 hover:bg-red-500/20 disabled:opacity-40 transition-colors"
              >
                Delete this version
              </button>
              <button
                onClick={() => setViewingVersion(null)}
                className="px-2.5 py-1 rounded text-[11px] text-white/40 hover:text-white/60 transition-colors"
              >
                Back to current
              </button>
            </div>
          </div>
        )}

        {editing ? (
          <div className="space-y-2">
            <textarea
              value={editContent}
              onChange={(e) => setEditContent(e.target.value)}
              className="w-full min-h-[200px] bg-white/5 border border-white/10 rounded-md p-3 text-sm text-white/80 leading-relaxed font-sans resize-y focus:outline-none focus:border-white/20"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={handleCancelEdit}
                className="px-3 py-1.5 rounded text-[11px] text-white/40 hover:text-white/60 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={handleSaveEdit}
                disabled={saving}
                className="px-3 py-1.5 rounded text-[11px] bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 disabled:opacity-40 transition-colors"
              >
                {saving ? 'Saving...' : 'Save as new version'}
              </button>
            </div>
          </div>
        ) : displayed ? (
          <pre className="text-sm text-white/80 whitespace-pre-wrap leading-relaxed font-sans">
            {displayed.content}
          </pre>
        ) : (
          <p className="text-[13px] text-white/20 text-center py-6">
            No memory body yet — trigger a dream to generate one
          </p>
        )}

        {versions.length > 0 && (
          <div className="pt-3 border-t border-white/5">
            <p className="text-[11px] text-white/30 mb-2">Version history</p>
            <div className="flex flex-wrap gap-1.5">
              {versions.map((v) => {
                const isCurrent = body ? v.version === body.version : false
                const isViewing = viewingVersion ? v.version === viewingVersion.version : false
                const isLoading = loadingVersion === v.version
                return (
                  <button
                    key={v.version}
                    onClick={() => handleLoadVersion(v.version)}
                    disabled={isLoading}
                    title={`${v.token_count} tokens · ${new Date(v.created_at).toLocaleString()}`}
                    className={[
                      'px-2 py-0.5 rounded text-[11px] transition-colors',
                      isCurrent && !isViewing
                        ? 'bg-white/10 text-white/70'
                        : isViewing
                        ? 'bg-amber-500/20 text-amber-400'
                        : 'bg-white/5 text-white/40 hover:bg-white/10 hover:text-white/60',
                    ].join(' ')}
                  >
                    {isLoading ? '…' : `v${v.version}`}
                  </button>
                )
              })}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
