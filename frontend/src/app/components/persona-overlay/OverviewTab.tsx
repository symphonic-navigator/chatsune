import { useEffect, useState } from 'react'
import type { ChakraPaletteEntry } from '../../../core/types/chakra'
import type { PersonaDto } from '../../../core/types/persona'
import { personasApi } from '../../../core/api/personas'
import { useAvatarSrc } from '../../../core/hooks/useAvatarSrc'
import { AvatarCropModal } from '../avatar-crop/AvatarCropModal'
import { CroppedAvatar } from '../avatar-crop/CroppedAvatar'
import type { ProfileCrop } from '../../../core/types/persona'

interface OverviewTabProps {
  persona: PersonaDto
  chakra: ChakraPaletteEntry
  onContinue: () => void
  onNewChat: () => void
  onNewIncognitoChat: () => void
  hasLastChat: boolean
  chatCount: number
  onGoToHistory: () => void
}

export function OverviewTab({ persona, chakra, onContinue, onNewChat, onNewIncognitoChat, hasLastChat, chatCount, onGoToHistory }: OverviewTabProps) {
  const [preview, setPreview] = useState<string | null>(null)
  const [expanded, setExpanded] = useState(false)
  const [cropOpen, setCropOpen] = useState(false)

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

  return (
    <div className="flex flex-col items-center px-6 py-8 gap-6">
      {/* Avatar — clickable to change */}
      <button
        type="button"
        onClick={() => setCropOpen(true)}
        className="group relative rounded-full flex-shrink-0 cursor-pointer"
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

      {/* Name + tagline */}
      <div className="flex flex-col items-center gap-1 text-center">
        <h2 className="text-[18px] font-semibold text-white/90">{persona.name}</h2>
        {persona.tagline && (
          <p className="text-[13px] text-white/45 max-w-xs">{persona.tagline}</p>
        )}
      </div>

      {/* Stats grid */}
      <div
        className="grid grid-cols-3 w-full max-w-sm rounded-xl overflow-hidden"
        style={{ border: `1px solid ${chakra.hex}22` }}
      >
        {[
          { label: 'Chats', value: String(chatCount), onClick: onGoToHistory },
          { label: 'Memory tokens', value: '\u2014' },
          { label: 'Pending journal', value: '\u2014' },
        ].map((stat, i) => (
          <div
            key={stat.label}
            className={`flex flex-col items-center gap-1 py-4 px-2${stat.onClick ? ' cursor-pointer hover:brightness-125 transition-all' : ''}`}
            style={{
              background: `${chakra.hex}08`,
              borderRight: i < 2 ? `1px solid ${chakra.hex}22` : undefined,
            }}
            onClick={stat.onClick}
          >
            <span className="text-[18px] font-semibold text-white/70">{stat.value}</span>
            <span className="text-[10px] text-white/35 text-center leading-tight">{stat.label}</span>
          </div>
        ))}
      </div>

      {/* Action buttons */}
      <div className="flex gap-2 w-full max-w-sm">
        <button
          type="button"
          onClick={onContinue}
          disabled={!hasLastChat}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all"
          style={{
            background: hasLastChat ? `${chakra.hex}18` : 'rgba(255,255,255,0.03)',
            border: `1px solid ${hasLastChat ? chakra.hex + '40' : 'rgba(255,255,255,0.06)'}`,
            color: hasLastChat ? `${chakra.hex}cc` : 'rgba(255,255,255,0.2)',
            cursor: hasLastChat ? 'pointer' : 'not-allowed',
          }}
        >
          Continue
        </button>
        <button
          type="button"
          onClick={onNewChat}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all hover:brightness-110"
          style={{
            background: `${chakra.hex}18`,
            border: `1px solid ${chakra.hex}40`,
            color: `${chakra.hex}cc`,
            cursor: 'pointer',
          }}
        >
          New Chat
        </button>
        <button
          type="button"
          onClick={onNewIncognitoChat}
          className="flex-1 rounded-lg py-2.5 text-[12px] font-medium transition-all hover:brightness-110"
          style={{
            background: 'rgba(255,255,255,0.04)',
            border: '1px solid rgba(255,255,255,0.08)',
            color: 'rgba(255,255,255,0.45)',
            cursor: 'pointer',
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
      <p className="text-[11px] text-white/25 font-mono">
        created {createdDate}
      </p>
    </div>
  )
}
