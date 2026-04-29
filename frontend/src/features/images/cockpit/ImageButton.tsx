import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { CockpitButton } from '@/features/chat/cockpit/CockpitButton'
import { useCockpitSession, useCockpitStore } from '@/features/chat/cockpit/cockpitStore'
import { useImagesStore } from '../store'
import { ImageConfigPanel } from './ImageConfigPanel'
import type { ActiveImageConfigDto } from '@/core/api/images'
import { eventBus } from '@/core/websocket/eventBus'
import { Topics } from '@/core/types/events'

type Props = {
  sessionId: string
  /**
   * Invoked when the button is clicked while no image-capable connection is
   * configured. Should navigate the user to the LLM Providers tab of the
   * user modal so they can add an xAI (or other TTI) connection.
   */
  onOpenLlmProviders: () => void
}

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

/**
 * Cockpit button for image-generation config.
 *
 * Three visual states:
 *   - "disabled" — no TTI/ITI connection is configured. Click navigates to
 *     the LLM Providers tab; no panel.
 *   - "idle"     — a TTI connection exists but the per-session Tools toggle
 *     is off, so image generation cannot actually run yet. Panel shows a
 *     hint with an "Enable Tools" action above the existing config UI.
 *   - "active"   — TTI available and Tools on. Behaves as before (purple).
 *
 * Uses click-to-toggle (not hover) so the panel stays open while the user
 * adjusts settings. The panel is rendered via a React portal into document.body
 * so it works correctly both on desktop and inside CockpitGroupButton on mobile
 * (where hover panels are suppressed and the group's close-on-click would
 * otherwise destroy a child-rendered panel).
 *
 * stopPropagation on the button click prevents CockpitGroupButton from
 * interpreting the tap as "close the group".
 */
export function ImageButton({ sessionId, onOpenLlmProviders }: Props) {
  const { available, active, loadConfig } = useImagesStore()
  const cockpit = useCockpitSession(sessionId)
  const setTools = useCockpitStore((s) => s.setTools)

  const [panelOpen, setPanelOpen] = useState(false)
  const buttonRef = useRef<HTMLDivElement | null>(null)
  const panelRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    void loadConfig()
  }, [loadConfig])

  // Re-fetch the TTI/ITI capability list whenever the underlying provider
  // state changes — both Premium provider accounts (xAI lives here) and
  // LLM connections (homelab Ollama etc.) feed into the available list.
  // Subscribing to one family is not enough: xAI keys are managed as
  // Premium accounts, so an xAI add/remove only fires
  // providers.account.upserted/deleted, never llm.connection.*.
  // Same pattern as useEnrichedModels.
  useEffect(() => {
    const topics = [
      Topics.LLM_CONNECTION_CREATED,
      Topics.LLM_CONNECTION_UPDATED,
      Topics.LLM_CONNECTION_REMOVED,
      Topics.LLM_CONNECTION_MODELS_REFRESHED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_UPSERTED,
      Topics.PREMIUM_PROVIDER_ACCOUNT_DELETED,
      Topics.PREMIUM_PROVIDER_MODELS_REFRESHED,
    ] as const
    const unsubs = topics.map((t) => eventBus.on(t, () => { void loadConfig() }))
    return () => unsubs.forEach((u) => u())
  }, [loadConfig])

  // Close on outside click or Escape.
  useEffect(() => {
    if (!panelOpen) return

    const onDocClick = (e: MouseEvent) => {
      const target = e.target as Node
      if (buttonRef.current?.contains(target)) return
      if (panelRef.current?.contains(target)) return
      setPanelOpen(false)
    }

    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPanelOpen(false)
    }

    document.addEventListener('mousedown', onDocClick)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDocClick)
      document.removeEventListener('keydown', onKey)
    }
  }, [panelOpen])

  const noConnection = available.length === 0
  const toolsOn = cockpit?.tools === true
  const badgeLabel = active ? humanModelLabel(active) : null

  const label = noConnection
    ? 'Image generation — no connection configured'
    : active
      ? `Image · ${badgeLabel}`
      : 'Image generation'

  // Visual state mapping — colour reflects runtime reality, not panel state:
  //   - no connection                  → "disabled" (dashed muted)
  //   - tools on                       → "active" (bright purple)
  //   - tools off (but TTI available)  → "idle" (white-ish)
  // Deliberately NOT promoting panelOpen to "active": with tools off the
  // pipeline cannot run, and a purple button next to a panel saying
  // "Tools are off" would contradict itself.
  const buttonState = noConnection
    ? 'disabled'
    : toolsOn
      ? 'active'
      : 'idle'

  const handleClick = () => {
    if (noConnection) {
      onOpenLlmProviders()
      return
    }
    setPanelOpen((v) => !v)
  }

  // Compute panel position relative to the button (above it, centred).
  // Falls back gracefully if the ref is not yet attached.
  const panelStyle = (): React.CSSProperties => {
    if (!buttonRef.current) return { position: 'fixed', bottom: 0, left: 0 }
    const rect = buttonRef.current.getBoundingClientRect()
    return {
      position: 'fixed',
      // Place the bottom of the panel 8 px above the top of the button.
      bottom: window.innerHeight - rect.top + 8,
      left: Math.max(8, rect.left + rect.width / 2 - 160),
    }
  }

  // Panel is suppressed entirely when there is no connection — the click
  // navigates to the LLM Providers modal instead, so the panel would be
  // redundant.
  const showPanel = panelOpen && !noConnection

  return (
    // stopPropagation on the wrapper div prevents CockpitGroupButton's
    // close-on-child-click from firing when this button is rendered inside
    // the mobile group.
    <div
      ref={buttonRef}
      onClick={(e) => e.stopPropagation()}
    >
      <CockpitButton
        icon={<ImageIcon />}
        state={buttonState}
        accent="purple"
        label={label}
        onClick={handleClick}
        ariaLabel={label}
      />
      {showPanel && createPortal(
        <div
          ref={panelRef}
          style={panelStyle()}
          className="z-50 w-80 rounded-lg border border-white/10 bg-[#1a1625] p-3 text-sm shadow-xl"
          role="dialog"
          aria-label="Image generation settings"
          onMouseDown={(e) => e.stopPropagation()}
        >
          {!toolsOn && (
            <div className="mb-3 rounded-md border border-white/10 bg-white/5 p-2 text-xs text-white/70">
              <p className="mb-2">
                Tools are off — image generation won't run yet.
              </p>
              <button
                type="button"
                className="rounded border border-[#a855f7]/40 bg-[#a855f7]/15 px-2 py-1 text-[#c084fc] hover:bg-[#a855f7]/25"
                onClick={() => {
                  void setTools(sessionId, true)
                }}
              >
                Enable Tools
              </button>
            </div>
          )}
          <ImageConfigPanel />
        </div>,
        document.body,
      )}
    </div>
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
