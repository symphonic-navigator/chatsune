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
  const committedEntries = useMemoryStore((s) => s.committedEntries[personaId] ?? [])
  const setMemoryBody = useMemoryStore((s) => s.setMemoryBody)
  const setBodyVersions = useMemoryStore((s) => s.setBodyVersions)

  const [body, setBody] = useState<MemoryBodyDto | null>(null)
  const [versions, setVersions] = useState<MemoryBodyVersionDto[]>([])
  const [viewingVersion, setViewingVersion] = useState<MemoryBodyDto | null>(null)
  const [busy, setBusy] = useState(false)
  const [loadingVersion, setLoadingVersion] = useState<number | null>(null)

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

  useEffect(() => {
    const cancelled = { value: false }
    loadBodyAndVersions(cancelled)
    return () => { cancelled.value = true }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [personaId, setMemoryBody, setBodyVersions])

  const prevIsDreaming = useRef(isDreaming)
  useEffect(() => {
    if (prevIsDreaming.current && !isDreaming) {
      const cancelled = { value: false }
      loadBodyAndVersions(cancelled)
    }
    prevIsDreaming.current = isDreaming
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isDreaming])

  const handleDream = async () => {
    if (busy || isDreaming || committedEntries.length === 0) return
    setBusy(true)
    try {
      await memoryApi.triggerDream(personaId)
    } finally {
      setBusy(false)
    }
  }

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

  const handleRollback = async () => {
    if (!viewingVersion || busy) return
    setBusy(true)
    try {
      await memoryApi.rollbackBody(personaId, viewingVersion.version)
      setViewingVersion(null)
    } finally {
      setBusy(false)
    }
  }

  const displayed = viewingVersion ?? body
  const isViewingOld = viewingVersion !== null && body !== null && viewingVersion.version !== body.version
  const dreamDisabled = busy || isDreaming || committedEntries.length === 0

  return (
    <div className="rounded-lg border border-white/5 bg-surface overflow-hidden">
      <div className="flex items-center justify-between px-4 py-3 border-b border-white/5">
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/60 font-medium">Memory Body</span>
          {displayed && (
            <span className="text-[11px] text-white/30">
              {displayed.token_count} / {TOKEN_LIMIT} tokens
            </span>
          )}
          {isDreaming && (
            <span className="flex items-center gap-1.5 text-[11px] text-purple-400">
              <svg className="animate-spin w-3 h-3" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
              </svg>
              Dreaming…
            </span>
          )}
        </div>
        <button
          onClick={handleDream}
          disabled={dreamDisabled}
          className="px-3 py-1 rounded text-xs bg-purple-500/10 text-purple-400 hover:bg-purple-500/20 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
        >
          Dream Now
        </button>
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
                disabled={busy}
                className="px-2.5 py-1 rounded text-[11px] bg-amber-500/10 text-amber-400 hover:bg-amber-500/20 disabled:opacity-40 transition-colors"
              >
                Rollback to this version
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

        {displayed ? (
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
