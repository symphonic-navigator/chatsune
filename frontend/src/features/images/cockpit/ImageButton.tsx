import { useEffect } from 'react'
import { CockpitButton } from '@/features/chat/cockpit/CockpitButton'
import { useImagesStore } from '../store'
import { ImageConfigPanel } from './ImageConfigPanel'
import type { ActiveImageConfigDto } from '@/core/api/images'

/**
 * Derives a short human-readable label from the active image config.
 * Examples: "imagine · pro", "imagine · normal"
 */
function humanModelLabel(active: ActiveImageConfigDto): string {
  const group = active.group_id.replace('xai_', '')
  const config = active.config as Record<string, unknown>
  const tier = typeof config.tier === 'string' ? config.tier : null
  return tier ? `${group} · ${tier}` : group
}

export function ImageButton() {
  const { available, active, loadConfig } = useImagesStore()

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  const disabled = available.length === 0
  const badgeLabel = active ? humanModelLabel(active) : null

  const label = disabled
    ? 'Image generation — no connection configured'
    : active
      ? `Image · ${badgeLabel}`
      : 'Image generation'

  return (
    <CockpitButton
      icon={<ImageIcon />}
      state={active ? 'active' : disabled ? 'disabled' : 'idle'}
      accent="purple"
      label={label}
      panel={
        disabled ? (
          <p className="text-white/70 text-xs">
            No image-capable connection configured. Add an xAI connection in settings.
          </p>
        ) : (
          <ImageConfigPanel />
        )
      }
    />
  )
}

/**
 * Simple camera/image SVG icon — matches the 16×16 size used by MicIcon in VoiceButton.
 */
function ImageIcon() {
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" fill="none" aria-hidden="true">
      {/* Camera body */}
      <rect x="1" y="4" width="14" height="10" rx="2" stroke="currentColor" strokeWidth="1.3" />
      {/* Lens circle */}
      <circle cx="8" cy="9" r="2.8" stroke="currentColor" strokeWidth="1.3" />
      {/* Viewfinder bump */}
      <path d="M5.5 4L6.5 2h3l1 2" stroke="currentColor" strokeWidth="1.3" strokeLinejoin="round" />
      {/* Flash dot */}
      <circle cx="12.5" cy="6.5" r="0.8" fill="currentColor" />
    </svg>
  )
}
