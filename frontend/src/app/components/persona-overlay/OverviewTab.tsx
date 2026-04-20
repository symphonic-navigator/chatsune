import { useEffect, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { personasApi } from '../../../core/api/personas'
import { ApiError } from '../../../core/api/client'
import { useAvatarSrc } from '../../../core/hooks/useAvatarSrc'
import { useEnrichedModels } from '../../../core/hooks/useEnrichedModels'
import { useNotificationStore } from '../../../core/store/notificationStore'
import { triggerBlobDownload } from '../../../core/utils/download'
import { AvatarCropModal } from '../avatar-crop/AvatarCropModal'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import type { ProfileCrop } from '../../../core/types/persona'
import { PersonaCloneDialog } from './PersonaCloneDialog'
import { ExportPersonaModal } from './ExportPersonaModal'

interface OverviewTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onContinue: () => void
  onNewChat: () => void
  onNewIncognitoChat: () => void
  hasLastChat: boolean
  chatCount: number
  onGoToHistory: () => void
  onDelete: () => Promise<void>
}

export function OverviewTab({ persona, chakra, onContinue, onNewChat, onNewIncognitoChat, hasLastChat, chatCount, onGoToHistory, onDelete }: OverviewTabProps) {
  const [preview, setPreview] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [cropOpen, setCropOpen] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [cloneOpen, setCloneOpen] = useState(false)
  const [exportOpen, setExportOpen] = useState(false)
  const [exporting, setExporting] = useState(false)
  const addNotification = useNotificationStore((s) => s.addNotification)
  // Resolve the persona's model against the unified enriched-models hub so
  // premium-provider models (e.g. ``xai:grok-4.1-fast``) resolve correctly
  // — a bare ``listConnectionModels`` lookup would 404 for those.
  // ``loading`` stands in for the previous ``true`` default and prevents a
  // premature banner flash while the first fetch is in flight.
  const { findByUniqueId, loading: modelsLoading } = useEnrichedModels()
  const modelResolved =
    modelsLoading || !!(persona.model_unique_id && findByUniqueId(persona.model_unique_id))

  const canStartChat = modelResolved

  const createdDate = new Date(persona.created_at).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })

  useEffect(() => {
    let mounted = true
    personasApi.getSystemPromptPreview(persona.id).then(res => {
      if (mounted) setPreview(res.preview)
    }).catch(() => {
      if (mounted) setPreview(null)
    })
    return () => { mounted = false }
  }, [persona.id])

  const hasPreview = preview !== null && preview.trim().length > 0

  const avatarSrc = useAvatarSrc(persona.id, !!persona.profile_image, persona.updated_at)

  async function handleAvatarSave(blob: Blob | null, crop: ProfileCrop) {
    if (blob) {
      await personasApi.uploadAvatar(persona.id, blob, crop)
    } else {
      await personasApi.updateAvatarCrop(persona.id, crop)
    }
    setCropOpen(false)
  }

  async function handleAvatarRemove() {
    await personasApi.deleteAvatar(persona.id)
    setCropOpen(false)
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete()
    } catch {
      setDeleting(false)
      setConfirmDelete(false)
    }
  }

  async function handleExport(includeContent: boolean) {
    if (exporting) return
    setExporting(true)
    try {
      const { blob, filename } = await personasApi.exportPersona(persona.id, includeContent)
      triggerBlobDownload({ blob, filename })
      setExportOpen(false)
      addNotification({
        level: 'success',
        title: 'Export started',
        message: `${persona.name} downloaded as ${filename}.`,
      })
    } catch (err) {
      const message =
        err instanceof ApiError
          ? err.message
          : err instanceof Error
            ? err.message
            : 'Failed to export persona.'
      addNotification({
        level: 'error',
        title: 'Export failed',
        message,
      })
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="flex flex-col items-center px-6 py-8 gap-6">
      {/* Avatar — clickable to change */}
      <button
        type="button"
        onClick={() => setCropOpen(true)}
        className="group relative rounded-full flex-shrink-0 cursor-pointer"
        aria-label="Change profile picture"
        title="Change profile picture"
        style={{
          width: 120,
          height: 120,
          background: avatarSrc ? undefined : `${chakra.hex}22`,
          border: `2px solid ${chakra.hex}55`,
          boxShadow: `0 0 28px ${chakra.glow}`,
        }}
      >
        {avatarSrc ? (
          <CroppedAvatar
            personaId={persona.id}
            updatedAt={persona.updated_at}
            crop={persona.profile_crop}
            size={116}
            alt={persona.name}
          />
        ) : (
          <span
            className="flex items-center justify-center w-full h-full text-4xl font-bold select-none"
            style={{ color: chakra.hex }}
          >
            {persona.monogram}
          </span>
        )}
        {/* Hover overlay */}
        <div className="absolute inset-0 rounded-full bg-black/50 opacity-0 group-hover:opacity-100 transition-opacity flex items-center justify-center">
          <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="white" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="opacity-80">
            <path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z" />
            <circle cx="12" cy="13" r="4" />
          </svg>
        </div>
      </button>

      {/* Avatar crop modal */}
      <AvatarCropModal
        isOpen={cropOpen}
        onClose={() => setCropOpen(false)}
        onSave={handleAvatarSave}
        onRemove={handleAvatarRemove}
        hasExisting={!!persona.profile_image}
        currentImageUrl={avatarSrc}
        initialCrop={persona.profile_crop}
        accentColour={chakra.hex}
      />

      {cloneOpen && (
        <PersonaCloneDialog
          source={persona}
          onClose={() => setCloneOpen(false)}
          onCloned={() => setCloneOpen(false)}
        />
      )}

      {exportOpen && (
        <ExportPersonaModal
          personaName={persona.name}
          chakraHex={chakra.hex}
          busy={exporting}
          onCancel={() => setExportOpen(false)}
          onExport={handleExport}
        />
      )}

      {/* Name + tagline + model */}
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-[18px] font-semibold text-white/90">{persona.name}</h2>
        {persona.tagline && (
          <p className="text-[13px] text-white/45 max-w-xs">{persona.tagline}</p>
        )}
        <p
          className="font-mono text-[11px]"
          style={{ color: chakra.hex + '4d', letterSpacing: '0.5px' }}
        >
          {persona.model_unique_id ? persona.model_unique_id.split(':').slice(1).join(':') : 'no model'}
        </p>
      </div>

      {/* Stats */}
      <div
        className="w-full max-w-sm rounded-xl overflow-hidden cursor-pointer hover:brightness-125 transition-all"
        style={{ border: `1px solid ${chakra.hex}22` }}
        onClick={onGoToHistory}
      >
        <div
          className="flex flex-col items-center gap-1 py-4 px-2"
          style={{ background: `${chakra.hex}08` }}
        >
          <span className="text-[18px] font-semibold text-white/70">{String(chatCount)}</span>
          <span className="text-[10px] text-white/60 text-center leading-tight">Chats</span>
        </div>
      </div>

      {/* Missing-connection banner */}
      {!canStartChat && (
        <div className="w-full max-w-sm p-3 bg-yellow-700/20 border border-yellow-600/40 rounded text-sm text-yellow-200">
          This persona references a connection that no longer exists.
          Please pick a model again.
        </div>
      )}

      {/* Action buttons */}
      <div className="flex gap-2 w-full max-w-sm">
        <button
          type="button"
          onClick={onContinue}
          disabled={!hasLastChat || !canStartChat}
          title={!canStartChat ? 'Model unavailable — please pick a model again.' : undefined}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all"
          style={{
            background: hasLastChat && canStartChat ? `${chakra.hex}18` : 'rgba(255,255,255,0.03)',
            border: `1px solid ${hasLastChat && canStartChat ? chakra.hex + '40' : 'rgba(255,255,255,0.06)'}`,
            color: hasLastChat && canStartChat ? `${chakra.hex}cc` : 'rgba(255,255,255,0.2)',
            cursor: hasLastChat && canStartChat ? 'pointer' : 'not-allowed',
          }}
        >
          Continue
        </button>
        <button
          type="button"
          onClick={onNewChat}
          disabled={!canStartChat}
          title={!canStartChat ? 'Model unavailable — please pick a model again.' : undefined}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all hover:brightness-110"
          style={{
            background: canStartChat ? `${chakra.hex}18` : 'rgba(255,255,255,0.03)',
            border: `1px solid ${canStartChat ? chakra.hex + '40' : 'rgba(255,255,255,0.06)'}`,
            color: canStartChat ? `${chakra.hex}cc` : 'rgba(255,255,255,0.2)',
            cursor: canStartChat ? 'pointer' : 'not-allowed',
          }}
        >
          New Chat
        </button>
        <button
          type="button"
          onClick={onNewIncognitoChat}
          disabled={!canStartChat}
          title={!canStartChat ? 'Model unavailable — please pick a model again.' : undefined}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all hover:brightness-110"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: canStartChat ? 'rgba(255,255,255,0.45)' : 'rgba(255,255,255,0.2)',
            cursor: canStartChat ? 'pointer' : 'not-allowed',
          }}
        >
          Incognito
        </button>
      </div>

      {/* System prompt preview */}
      {hasPreview && (
        <div className="w-full max-w-sm">
          <div className="relative">
            <pre
              className="font-mono text-[12px] text-white/50 leading-relaxed whitespace-pre-wrap break-words m-0 overflow-hidden transition-[max-height] duration-300 ease-in-out"
              style={{
                maxHeight: expanded ? '60vh' : '4.5em',
                overflowY: expanded ? 'auto' : 'hidden',
              }}
            >
              {preview.split(/(--- .+? ---)/  ).map((part, i) =>
                part.match(/^--- .+? ---$/) ? (
                  <span key={i} style={{ color: chakra.hex, fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.15em' }}>
                    {part}
                  </span>
                ) : (
                  <span key={i}>{part}</span>
                )
              )}
            </pre>
            {!expanded && (
              <div
                className="absolute bottom-0 left-0 right-0 h-8 pointer-events-none"
                style={{
                  background: 'linear-gradient(to bottom, transparent, #0f0d16)',
                }}
              />
            )}
          </div>
          <button
            onClick={() => setExpanded(prev => !prev)}
            className="mt-2 font-mono text-[11px] text-white/35 hover:text-white/55 transition-colors cursor-pointer bg-transparent border-none p-0"
          >
            {expanded ? 'Collapse' : 'Show full prompt'}
          </button>
        </div>
      )}

      {/* Created date */}
      <p className="text-[11px] text-white/60 font-mono">
        created {createdDate}
      </p>

      {/* Persona actions */}
      <div className="w-full max-w-sm flex gap-2">
        <button
          type="button"
          onClick={() => setCloneOpen(true)}
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5"
        >
          Clone
        </button>
        <button
          type="button"
          onClick={() => setExportOpen(true)}
          disabled={exporting}
          title="Export this persona as a .chatsune-persona.tar.gz archive"
          className="flex-1 rounded-lg py-2 text-[12px] text-white/70 border border-white/10 hover:bg-white/5 disabled:opacity-50"
        >
          {exporting ? 'Exporting…' : 'Export'}
        </button>
      </div>

      {/* Danger zone — delete */}
      <div className="w-full max-w-sm mt-4 pt-4" style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
        {!confirmDelete ? (
          <button
            type="button"
            onClick={() => setConfirmDelete(true)}
            className="w-full rounded-lg py-2 text-[12px] font-medium text-red-400/60 transition-colors hover:bg-red-400/8 hover:text-red-400/80"
            style={{ border: '1px solid rgba(248,113,113,0.15)' }}
          >
            Delete persona
          </button>
        ) : (
          <div className="rounded-lg p-3" style={{ border: '1px solid rgba(248,113,113,0.25)', background: 'rgba(248,113,113,0.06)' }}>
            <p className="text-[12px] text-red-300/70 mb-3">
              This will permanently delete <strong className="text-red-300/90">{persona.name}</strong>, all chat history, memories, uploads and artefacts. This cannot be undone.
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleDelete}
                disabled={deleting}
                className="flex-1 rounded-lg py-2 text-[12px] font-medium text-white bg-red-500/80 hover:bg-red-500 transition-colors disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Delete permanently'}
              </button>
              <button
                type="button"
                onClick={() => setConfirmDelete(false)}
                disabled={deleting}
                className="px-3 rounded-lg py-2 text-[12px] text-white/50 hover:text-white/70 transition-colors disabled:opacity-50"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
