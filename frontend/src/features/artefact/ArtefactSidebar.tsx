import { useEffect, useRef, useState } from 'react'
import { useArtefactStore } from '../../core/store/artefactStore'
import { artefactApi } from '../../core/api/artefact'
import type { ArtefactSummary } from '../../core/types/artefact'
import { useViewport } from '../../core/hooks/useViewport'
import { lockBodyScroll, unlockBodyScroll } from '../../core/utils/bodyScrollLock'

const TYPE_COLOURS: Record<string, string> = {
  markdown: '180,180,220',
  code: '137,180,250',
  html: '250,170,130',
  svg: '170,220,170',
  jsx: '140,180,250',
  mermaid: '200,170,250',
}

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function getExtension(artefact: ArtefactSummary): string {
  switch (artefact.type) {
    case 'markdown': return '.md'
    case 'html': return '.html'
    case 'svg': return '.svg'
    case 'jsx': return '.jsx'
    case 'mermaid': return '.mmd'
    case 'code': return artefact.language ? `.${artefact.language}` : '.txt'
    default: return `.${artefact.type}`
  }
}

interface ContextMenuState {
  handle: string
  x: number
  y: number
}

interface ArtefactSidebarProps {
  sessionId: string
}

export function ArtefactSidebar({ sessionId }: ArtefactSidebarProps) {
  const { isDesktop } = useViewport()
  const artefacts = useArtefactStore((s) => s.artefacts)
  const toggleSidebar = useArtefactStore((s) => s.toggleSidebar)
  const setSidebarOpen = useArtefactStore((s) => s.setSidebarOpen)

  // Mobile sheet behaviours: body-scroll-lock while open, Esc closes.
  useEffect(() => {
    if (isDesktop) return
    lockBodyScroll()
    const handleKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSidebarOpen(false)
    }
    document.addEventListener('keydown', handleKey)
    return () => {
      document.removeEventListener('keydown', handleKey)
      unlockBodyScroll()
    }
  }, [isDesktop, setSidebarOpen])
  const openOverlay = useArtefactStore((s) => s.openOverlay)
  const removeArtefact = useArtefactStore((s) => s.removeArtefact)
  const updateArtefact = useArtefactStore((s) => s.updateArtefact)

  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const [renamingHandle, setRenamingHandle] = useState<string | null>(null)
  const [renameValue, setRenameValue] = useState('')
  const renameInputRef = useRef<HTMLInputElement>(null)

  const handleArtefactClick = async (artefact: ArtefactSummary) => {
    if (renamingHandle === artefact.handle) return
    try {
      const detail = await artefactApi.get(sessionId, artefact.handle)
      openOverlay(detail)
      if (!isDesktop) setSidebarOpen(false)
    } catch {
      // silently ignore — overlay stays closed
    }
  }

  const handleContextMenu = (e: React.MouseEvent, handle: string) => {
    e.preventDefault()
    e.stopPropagation()
    setContextMenu({ handle, x: e.clientX, y: e.clientY })
  }

  const closeContextMenu = () => setContextMenu(null)

  const startRename = (artefact: ArtefactSummary) => {
    setRenamingHandle(artefact.handle)
    setRenameValue(artefact.title)
    closeContextMenu()
    setTimeout(() => renameInputRef.current?.select(), 30)
  }

  const commitRename = async (handle: string) => {
    const trimmed = renameValue.trim()
    if (trimmed) {
      try {
        await artefactApi.patch(sessionId, handle, { title: trimmed })
        updateArtefact(handle, { title: trimmed })
      } catch {
        // ignore — title stays as is
      }
    }
    setRenamingHandle(null)
  }

  const handleCopy = async (artefact: ArtefactSummary) => {
    closeContextMenu()
    try {
      const detail = await artefactApi.get(sessionId, artefact.handle)
      await navigator.clipboard.writeText(detail.content)
    } catch {
      // silently ignore
    }
  }

  const handleDownload = async (artefact: ArtefactSummary) => {
    closeContextMenu()
    try {
      const detail = await artefactApi.get(sessionId, artefact.handle)
      const blob = new Blob([detail.content], { type: 'text/plain;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const anchor = document.createElement('a')
      anchor.href = url
      anchor.download = `${artefact.title}${getExtension(artefact)}`
      document.body.appendChild(anchor)
      anchor.click()
      document.body.removeChild(anchor)
      URL.revokeObjectURL(url)
    } catch {
      // silently ignore
    }
  }

  const handleDelete = async (artefact: ArtefactSummary) => {
    closeContextMenu()
    try {
      await artefactApi.delete(sessionId, artefact.handle)
      removeArtefact(artefact.handle)
    } catch {
      // silently ignore
    }
  }

  const contextArtefact = contextMenu
    ? artefacts.find((a) => a.handle === contextMenu.handle) ?? null
    : null

  return (
    <>
      {/* Mobile-only backdrop: click to dismiss the right-sheet. */}
      {!isDesktop && (
        <div
          className="fixed inset-0 z-30 bg-black/50"
          onClick={() => setSidebarOpen(false)}
          aria-hidden="true"
        />
      )}
      {/* Sidebar panel: in-flow on desktop, right-sheet on mobile. */}
      <div
        className={
          isDesktop
            ? 'flex w-[280px] flex-shrink-0 flex-col border-l border-white/6 bg-white/[0.01]'
            : 'fixed inset-y-0 right-0 z-40 flex w-[92vw] max-w-[440px] flex-col border-l border-white/10 bg-elevated shadow-2xl'
        }
      >
        {/* Header */}
        <div
          className="flex items-center justify-between border-b border-white/6 px-3 py-2 cursor-pointer lg:cursor-default"
          onClick={() => { if (!isDesktop) setSidebarOpen(false) }}
          role={isDesktop ? undefined : "button"}
        >
          <span className="text-[11px] font-mono text-white/40 tracking-wider uppercase">Artefacts</span>
          <button
            type="button"
            onClick={toggleSidebar}
            className="flex items-center justify-center rounded p-0.5 text-white/30 transition-colors hover:text-white/60"
            title="Collapse artefact panel"
          >
            <svg width="12" height="12" viewBox="0 0 10 10" fill="none">
              <path d="M4 1L8 5L4 9" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>

        {/* Artefact list */}
        <div className="flex flex-1 flex-col overflow-y-auto py-1">
          {artefacts.length === 0 ? (
            <div className="flex flex-1 items-center justify-center text-[11px] font-mono text-white/20">
              No artefacts
            </div>
          ) : (
            artefacts.map((artefact) => {
              const colour = TYPE_COLOURS[artefact.type] ?? '180,180,180'
              const isRenaming = renamingHandle === artefact.handle

              return (
                <div
                  key={artefact.handle}
                  className="group relative flex cursor-pointer items-start gap-2 px-3 py-2 transition-colors hover:bg-white/[0.03]"
                  onClick={() => handleArtefactClick(artefact)}
                >
                  {/* Type badge */}
                  <span
                    className="mt-px shrink-0 rounded px-1 py-px text-[9px] font-mono uppercase"
                    style={{
                      background: `rgba(${colour},0.1)`,
                      color: `rgba(${colour},0.85)`,
                      border: `1px solid rgba(${colour},0.2)`,
                    }}
                  >
                    {artefact.type === 'code' && artefact.language ? artefact.language : artefact.type}
                  </span>

                  {/* Title and size */}
                  <div className="min-w-0 flex-1">
                    {isRenaming ? (
                      <input
                        ref={renameInputRef}
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onBlur={() => commitRename(artefact.handle)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') commitRename(artefact.handle)
                          if (e.key === 'Escape') setRenamingHandle(null)
                          e.stopPropagation()
                        }}
                        onClick={(e) => e.stopPropagation()}
                        className="w-full rounded bg-white/8 px-1.5 py-0.5 text-[12px] text-white/80 outline-none ring-1 ring-white/20 focus:ring-white/40"
                        autoFocus
                      />
                    ) : (
                      <div className="truncate text-[12px] text-white/70 leading-snug">
                        {artefact.title}
                      </div>
                    )}
                    <div className="mt-0.5 text-[10px] font-mono text-white/25">
                      {formatBytes(artefact.size_bytes)}
                      {artefact.version > 1 && (
                        <span className="ml-1.5 text-white/20">v{artefact.version}</span>
                      )}
                    </div>
                  </div>

                  {/* Three-dot menu button */}
                  {!isRenaming && (
                    <button
                      type="button"
                      onClick={(e) => { e.stopPropagation(); handleContextMenu(e, artefact.handle) }}
                      className="mt-0.5 shrink-0 rounded p-0.5 text-white/20 opacity-0 transition-all group-hover:opacity-100 hover:bg-white/8 hover:text-white/50"
                      title="Options"
                    >
                      <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                        <circle cx="7" cy="3" r="1" />
                        <circle cx="7" cy="7" r="1" />
                        <circle cx="7" cy="11" r="1" />
                      </svg>
                    </button>
                  )}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Context menu */}
      {contextMenu && contextArtefact && (
        <>
          {/* Click-away backdrop */}
          <div
            className="fixed inset-0 z-40"
            onClick={closeContextMenu}
            onContextMenu={(e) => { e.preventDefault(); closeContextMenu() }}
          />
          <div
            className="fixed z-50 min-w-[140px] overflow-hidden rounded-lg py-1 shadow-2xl"
            style={{
              left: contextMenu.x,
              top: contextMenu.y,
              background: 'rgba(20,18,28,0.98)',
              border: '1px solid rgba(255,255,255,0.08)',
              boxShadow: '0 8px 32px rgba(0,0,0,0.6)',
            }}
          >
            {[
              { label: 'Rename', action: () => startRename(contextArtefact) },
              { label: 'Copy', action: () => handleCopy(contextArtefact) },
              { label: 'Download', action: () => handleDownload(contextArtefact) },
              { label: 'Delete', action: () => handleDelete(contextArtefact), danger: true },
            ].map(({ label, action, danger }) => (
              <button
                key={label}
                type="button"
                onClick={action}
                className={`w-full px-3 py-1.5 text-left text-[12px] transition-colors hover:bg-white/[0.05] ${
                  danger ? 'text-red-400/80 hover:text-red-400' : 'text-white/60 hover:text-white/90'
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        </>
      )}
    </>
  )
}
