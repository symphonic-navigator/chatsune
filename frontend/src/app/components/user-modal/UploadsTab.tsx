import { useCallback, useEffect, useRef, useState } from 'react'
import { storageApi } from '../../../core/api/storage'
import { currentAccessToken } from '../../../core/api/client'
import type { StorageFileDto, StorageQuotaDto } from '../../../core/api/storage'

type SortBy = 'date' | 'size'
type SortOrder = 'asc' | 'desc'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-1 font-mono"
const BTN = 'px-2.5 py-1 rounded-lg text-[11px] font-mono transition-all border cursor-pointer'
const BTN_NEUTRAL = `${BTN} border-white/8 text-white/40 hover:text-white/60 hover:border-white/15`
const BTN_ACTIVE = `${BTN} border-gold/60 bg-gold/12 text-gold`
const BTN_RED = `${BTN} border-red-400/30 text-red-400 bg-red-400/10 hover:bg-red-400/15`

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
}

function formatRelativeDate(iso: string): string {
  const date = new Date(iso)
  const now = Date.now()
  const diff = now - date.getTime()
  const seconds = Math.floor(diff / 1000)
  const minutes = Math.floor(seconds / 60)
  const hours = Math.floor(minutes / 60)
  const days = Math.floor(hours / 24)

  if (seconds < 60) return 'just now'
  if (minutes < 60) return `${minutes} min ago`
  if (hours < 24) return `${hours} hour${hours === 1 ? '' : 's'} ago`
  if (days === 1) return 'yesterday'
  if (days < 7) return `${days} days ago`
  return date.toLocaleDateString()
}

function quotaColour(percentage: number): string {
  if (percentage >= 90) return 'bg-red-400'
  if (percentage >= 80) return 'bg-orange-400'
  if (percentage >= 60) return 'bg-yellow-400'
  return 'bg-green-400'
}

function quotaTextColour(percentage: number): string {
  if (percentage >= 90) return 'text-red-400'
  if (percentage >= 80) return 'text-orange-400'
  if (percentage >= 60) return 'text-yellow-400'
  return 'text-green-400'
}

function fileIcon(mediaType: string): string {
  if (mediaType.startsWith('image/')) return '🖼'
  if (mediaType.startsWith('video/')) return '🎬'
  if (mediaType.startsWith('audio/')) return '🎵'
  if (mediaType === 'application/pdf') return '📄'
  if (mediaType.startsWith('text/')) return '📝'
  return '📎'
}

async function downloadFile(fileId: string, filename: string) {
  const token = currentAccessToken()
  const res = await fetch(storageApi.downloadUrl(fileId), {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    credentials: 'include',
  })
  if (!res.ok) return
  const blob = await res.blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

export function UploadsTab() {
  const [files, setFiles] = useState<StorageFileDto[]>([])
  const [quota, setQuota] = useState<StorageQuotaDto | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [sortBy, setSortBy] = useState<SortBy>('date')
  const [sortOrder, setSortOrder] = useState<SortOrder>('desc')
  const [deletingId, setDeletingId] = useState<string | null>(null)
  const [editingId, setEditingId] = useState<string | null>(null)
  const [editValue, setEditValue] = useState('')
  const editRef = useRef<HTMLInputElement>(null)

  const fetchData = useCallback(async (sort?: SortBy, order?: SortOrder) => {
    try {
      const [fileList, quotaData] = await Promise.all([
        storageApi.listFiles({ sort_by: sort ?? sortBy, order: order ?? sortOrder }),
        storageApi.getQuota(),
      ])
      setFiles(fileList)
      setQuota(quotaData)
      setError(null)
    } catch {
      setError('Failed to load uploads')
    } finally {
      setLoading(false)
    }
  }, [sortBy, sortOrder])

  useEffect(() => {
    fetchData()
  }, [fetchData])

  useEffect(() => {
    if (editingId && editRef.current) {
      editRef.current.focus()
      editRef.current.select()
    }
  }, [editingId])

  function handleSortBy(value: SortBy) {
    setSortBy(value)
    setLoading(true)
    fetchData(value, sortOrder)
  }

  function handleSortOrder() {
    const next = sortOrder === 'desc' ? 'asc' : 'desc'
    setSortOrder(next)
    setLoading(true)
    fetchData(sortBy, next)
  }

  function startRename(file: StorageFileDto) {
    setEditingId(file.id)
    setEditValue(file.display_name)
  }

  async function confirmRename(fileId: string) {
    const trimmed = editValue.trim()
    if (!trimmed) {
      setEditingId(null)
      return
    }
    try {
      const updated = await storageApi.renameFile(fileId, trimmed)
      setFiles((prev) => prev.map((f) => (f.id === fileId ? updated : f)))
    } catch {
      // Silently fail — the old name remains visible
    }
    setEditingId(null)
  }

  function cancelRename() {
    setEditingId(null)
  }

  async function confirmDelete(fileId: string) {
    try {
      await storageApi.deleteFile(fileId)
      setFiles((prev) => prev.filter((f) => f.id !== fileId))
      setDeletingId(null)
      // Refresh quota after deletion
      const quotaData = await storageApi.getQuota()
      setQuota(quotaData)
    } catch {
      setError('Failed to delete file')
      setDeletingId(null)
    }
  }

  if (loading && files.length === 0) {
    return (
      <div className="flex flex-1 items-center justify-center text-[13px] text-white/25 font-mono">
        Loading uploads...
      </div>
    )
  }

  if (error && files.length === 0) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-3">
        <p className="text-[13px] text-red-400 font-mono">{error}</p>
        <button
          type="button"
          onClick={() => { setLoading(true); setError(null); fetchData() }}
          className={BTN_NEUTRAL}
        >
          Retry
        </button>
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-4 p-6 h-full">
      {/* Quota bar */}
      {quota && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className={LABEL}>Storage</span>
            <span className={`text-[11px] font-mono ${quotaTextColour(quota.percentage)}`}>
              {formatSize(quota.used_bytes)} / {formatSize(quota.limit_bytes)} ({quota.percentage.toFixed(0)}%)
            </span>
          </div>
          <div className="h-1.5 rounded-full bg-white/6 overflow-hidden">
            <div
              className={`h-full rounded-full transition-all ${quotaColour(quota.percentage)}`}
              style={{ width: `${Math.min(quota.percentage, 100)}%` }}
            />
          </div>
        </div>
      )}

      {/* Controls row */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* TODO: Persona filter dropdown — requires persona list, skipped for now */}

        <div className="flex items-center gap-1.5">
          <span className="text-[10px] text-white/30 font-mono uppercase tracking-wider mr-1">Sort</span>
          <button
            type="button"
            onClick={() => handleSortBy('date')}
            className={sortBy === 'date' ? BTN_ACTIVE : BTN_NEUTRAL}
          >
            Date
          </button>
          <button
            type="button"
            onClick={() => handleSortBy('size')}
            className={sortBy === 'size' ? BTN_ACTIVE : BTN_NEUTRAL}
          >
            Size
          </button>
        </div>

        <button
          type="button"
          onClick={handleSortOrder}
          className={BTN_NEUTRAL}
          title={sortOrder === 'desc' ? 'Descending' : 'Ascending'}
        >
          {sortOrder === 'desc' ? '↓ Desc' : '↑ Asc'}
        </button>

        <span className="ml-auto text-[11px] text-white/25 font-mono">
          {files.length} file{files.length !== 1 ? 's' : ''}
        </span>
      </div>

      {/* File list */}
      {files.length === 0 ? (
        <div className="flex flex-1 items-center justify-center text-[13px] text-white/25 font-mono">
          No files uploaded yet
        </div>
      ) : (
        <div className="flex-1 overflow-y-auto -mx-1 px-1">
          <div className="flex flex-col gap-1">
            {files.map((file) => (
              <div
                key={file.id}
                className="flex items-center gap-3 px-3 py-2.5 rounded-lg border border-white/6 hover:border-white/10 transition-colors group"
              >
                {/* Thumbnail or icon */}
                <div className="w-8 h-8 rounded flex items-center justify-center flex-shrink-0 bg-white/4 overflow-hidden">
                  {file.thumbnail_b64 ? (
                    <img
                      src={`data:${file.media_type};base64,${file.thumbnail_b64}`}
                      alt=""
                      className="w-8 h-8 object-cover rounded"
                    />
                  ) : (
                    <span className="text-sm">{fileIcon(file.media_type)}</span>
                  )}
                </div>

                {/* Name column */}
                <div className="flex flex-col min-w-0 flex-1">
                  {editingId === file.id ? (
                    <input
                      ref={editRef}
                      type="text"
                      value={editValue}
                      onChange={(e) => setEditValue(e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter') confirmRename(file.id)
                        if (e.key === 'Escape') cancelRename()
                      }}
                      onBlur={() => confirmRename(file.id)}
                      className="bg-white/6 border border-white/10 rounded px-1.5 py-0.5 text-[12px] text-white/90 font-mono outline-none focus:border-gold/40 w-full"
                    />
                  ) : (
                    <button
                      type="button"
                      onClick={() => startRename(file)}
                      className="text-left text-[12px] text-white/80 font-mono truncate hover:text-white cursor-text"
                      title="Click to rename"
                    >
                      {file.display_name}
                    </button>
                  )}
                  {file.original_name !== file.display_name && (
                    <span className="text-[10px] text-white/25 font-mono truncate">
                      {file.original_name}
                    </span>
                  )}
                </div>

                {/* Size */}
                <span className="text-[11px] text-white/30 font-mono whitespace-nowrap flex-shrink-0">
                  {formatSize(file.size_bytes)}
                </span>

                {/* Date */}
                <span className="text-[11px] text-white/25 font-mono whitespace-nowrap flex-shrink-0 w-20 text-right">
                  {formatRelativeDate(file.created_at)}
                </span>

                {/* Actions */}
                <div className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity">
                  {deletingId === file.id ? (
                    <>
                      <span className="text-[10px] text-red-400 font-mono mr-1">Delete?</span>
                      <button
                        type="button"
                        onClick={() => confirmDelete(file.id)}
                        className={BTN_RED}
                      >
                        Yes
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeletingId(null)}
                        className={BTN_NEUTRAL}
                      >
                        No
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => downloadFile(file.id, file.display_name)}
                        className={BTN_NEUTRAL}
                        title="Download"
                      >
                        ↓
                      </button>
                      <button
                        type="button"
                        onClick={() => setDeletingId(file.id)}
                        className={BTN_NEUTRAL}
                        title="Delete"
                      >
                        ✕
                      </button>
                    </>
                  )}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}
