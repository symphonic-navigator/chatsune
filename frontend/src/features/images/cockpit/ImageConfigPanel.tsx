import { useState, useEffect, useRef } from 'react'
import type { ImageGroupConfig, XaiImagineConfig } from '@/core/api/images'
import { useImagesStore } from '../store'
import { imagesApi } from '../api'
import { IMAGE_GROUP_VIEWS } from '../groups/registry'

// Default config for xai_imagine when no saved config exists.
const XAI_IMAGINE_DEFAULTS: XaiImagineConfig = {
  group_id: 'xai_imagine',
  tier: 'normal',
  resolution: '1k',
  aspect: '1:1',
  n: 4,
}

function defaultConfigForGroup(groupId: string): ImageGroupConfig {
  if (groupId === 'xai_imagine') return { ...XAI_IMAGINE_DEFAULTS }
  // Extend this when new groups are added (Seedream, FLUX, etc.)
  return { ...XAI_IMAGINE_DEFAULTS }
}

// Format a short human-readable label for a group id.
function groupLabel(groupId: string): string {
  return groupId.replace(/_/g, ' ')
}

/** Option style applied to native <select> options — see CLAUDE.md for why. */
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

// --- empty state -------------------------------------------------------------

function EmptyState() {
  return (
    <p className="text-xs text-white/50 leading-relaxed">
      No image-capable connection configured.{' '}
      <span className="text-white/70">Add an xAI connection in settings.</span>
    </p>
  )
}

// --- main panel --------------------------------------------------------------

export function ImageConfigPanel() {
  const { available, active } = useImagesStore()

  // Working state: the three values the user is editing right now.
  const [connectionId, setConnectionId] = useState<string>('')
  const [groupId, setGroupId] = useState<string>('')
  const [config, setConfig] = useState<ImageGroupConfig>(XAI_IMAGINE_DEFAULTS)

  // Auto-save state
  const [savingState, setSavingState] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle')
  const [saveError, setSaveError] = useState<string | null>(null)

  // Test-image state
  const [testing, setTesting] = useState(false)
  const [testImages, setTestImages] = useState<string[]>([])
  const [testError, setTestError] = useState<string | null>(null)

  const applyConfig = useImagesStore((s) => s.applyConfig)

  // Skip the very first effect run after mount so opening the panel doesn't
  // trigger a redundant save with the already-active config.
  const isFirstAfterMount = useRef(true)

  // Hydrate exactly once per mount. After the initial population the user owns
  // the working state — re-hydrating from `active` would feed a save → store
  // update → re-hydrate → save loop, because our own `applyConfig` call
  // updates `active` with a fresh object reference.
  const hydratedRef = useRef(false)

  // Hydrate from the active config or fall back to the first available connection.
  useEffect(() => {
    if (hydratedRef.current) return
    if (available.length === 0) return

    if (active) {
      setConnectionId(active.connection_id)
      setGroupId(active.group_id)
      // Attempt to cast the raw config object. If the group_id matches we trust it.
      // Double-cast via unknown because ActiveImageConfigDto.config is Record<string,unknown>.
      const raw = active.config as Record<string, unknown>
      if (raw.group_id === active.group_id) {
        setConfig(raw as unknown as ImageGroupConfig)
      } else {
        setConfig(defaultConfigForGroup(active.group_id))
      }
    } else {
      const first = available[0]
      const firstGroup = first.group_ids[0] ?? 'xai_imagine'
      setConnectionId(first.connection_id)
      setGroupId(firstGroup)
      setConfig(defaultConfigForGroup(firstGroup))
    }

    hydratedRef.current = true
  }, [available, active])

  // Auto-save with 400 ms debounce. Skips the first run after mount so the
  // initial hydration does not trigger an unnecessary network call.
  useEffect(() => {
    if (!connectionId || !groupId) return

    if (isFirstAfterMount.current) {
      isFirstAfterMount.current = false
      return
    }

    const timer = setTimeout(async () => {
      setSavingState('saving')
      setSaveError(null)
      try {
        await applyConfig({ connection_id: connectionId, group_id: groupId, config })
        setSavingState('saved')
        // Clear the "Saved" indicator after 1.5 s.
        setTimeout(() => setSavingState((s) => (s === 'saved' ? 'idle' : s)), 1500)
      } catch (err) {
        setSavingState('error')
        setSaveError(err instanceof Error ? err.message : 'Failed to save')
      }
    }, 400)

    return () => clearTimeout(timer)
  }, [connectionId, groupId, config, applyConfig])

  if (available.length === 0) {
    return <EmptyState />
  }

  // The connection object for the currently selected connection_id.
  const selectedConnection = available.find((c) => c.connection_id === connectionId) ?? available[0]
  const availableGroups = selectedConnection?.group_ids ?? []

  const handleConnectionChange = (newConnectionId: string) => {
    setConnectionId(newConnectionId)
    const conn = available.find((c) => c.connection_id === newConnectionId)
    const firstGroup = conn?.group_ids[0] ?? 'xai_imagine'
    setGroupId(firstGroup)
    setConfig(defaultConfigForGroup(firstGroup))
    // Clear test results on connection change.
    setTestImages([])
    setTestError(null)
  }

  const handleGroupChange = (newGroupId: string) => {
    setGroupId(newGroupId)
    setConfig(defaultConfigForGroup(newGroupId))
    setTestImages([])
    setTestError(null)
  }

  const handleTest = async () => {
    setTesting(true)
    setTestImages([])
    setTestError(null)
    try {
      const result = await imagesApi.testImagine({
        connection_id: connectionId,
        group_id: groupId,
        config,
        prompt: 'A beautiful golden sunset over calm ocean waves',
      })
      if (result.thumbs_data_uris.length === 0) {
        if (result.moderated_count > 0) {
          setTestError(`All ${result.moderated_count} results were moderated. Try a different prompt.`)
        } else {
          setTestError('Generation completed but produced no images.')
        }
      } else {
        setTestImages(result.thumbs_data_uris)
      }
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Test request failed.'
      setTestError(msg)
    } finally {
      setTesting(false)
    }
  }

  // Resolve the config view component for this group.
  const ConfigView = IMAGE_GROUP_VIEWS[groupId]

  return (
    <div className="space-y-3">
      {/* Header */}
      <div className="text-[10px] uppercase tracking-wider text-white/40">
        Image generation
      </div>

      {/* Connection selector */}
      {available.length === 1 ? (
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-white/50">Connection</span>
          <span className="text-[11px] text-white/85">{selectedConnection.connection_display_name}</span>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-white/50 shrink-0">Connection</span>
          <select
            value={connectionId}
            onChange={(e) => handleConnectionChange(e.target.value)}
            className="text-[11px] bg-[#1a1625] border border-white/15 rounded px-2 py-1 text-white/85 focus:outline-none focus:border-[#c084fc]/50"
          >
            {available.map((c) => (
              <option key={c.connection_id} value={c.connection_id} style={OPTION_STYLE}>
                {c.connection_display_name}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Group selector */}
      {availableGroups.length <= 1 ? (
        <div className="flex items-center justify-between">
          <span className="text-[11px] text-white/50">Group</span>
          <span className="text-[11px] text-white/85">{groupLabel(groupId)}</span>
        </div>
      ) : (
        <div className="flex items-center justify-between gap-2">
          <span className="text-[11px] text-white/50 shrink-0">Group</span>
          <select
            value={groupId}
            onChange={(e) => handleGroupChange(e.target.value)}
            className="text-[11px] bg-[#1a1625] border border-white/15 rounded px-2 py-1 text-white/85 focus:outline-none focus:border-[#c084fc]/50"
          >
            {availableGroups.map((g) => (
              <option key={g} value={g} style={OPTION_STYLE}>
                {groupLabel(g)}
              </option>
            ))}
          </select>
        </div>
      )}

      {/* Divider */}
      <div className="border-t border-white/8" />

      {/* Group-specific config view */}
      {ConfigView ? (
        <ConfigView config={config} onChange={setConfig} />
      ) : (
        <p className="text-xs text-white/40 italic">No config view for group "{groupId}".</p>
      )}

      {/* Divider */}
      <div className="border-t border-white/8" />

      {/* Test image thumbnails */}
      {testImages.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {testImages.map((url) => (
            <img
              key={url}
              src={url}
              alt="Test result"
              className="w-14 h-14 object-cover rounded border border-white/10"
            />
          ))}
        </div>
      )}

      {/* Test error */}
      {testError && (
        <p className="text-[11px] text-red-300/80 leading-snug">{testError}</p>
      )}

      {/* Action row: Test button + auto-save indicator */}
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => { void handleTest() }}
          disabled={testing}
          className="flex-1 text-[11px] px-2 py-1.5 rounded border border-white/15 bg-white/5 text-white/70 hover:bg-white/10 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          {testing ? (
            <span className="flex items-center justify-center gap-1.5">
              <SpinnerIcon />
              Testing…
            </span>
          ) : (
            'Test image'
          )}
        </button>

        {/* Auto-save status indicator */}
        <span className="text-[11px] min-w-[52px] text-right">
          {savingState === 'saving' && (
            <span className="flex items-center gap-1 text-white/40">
              <SpinnerIcon />
              Saving…
            </span>
          )}
          {savingState === 'saved' && (
            <span className="text-white/40">&#10003; Saved</span>
          )}
          {savingState === 'error' && saveError && (
            <span className="text-red-400">{saveError}</span>
          )}
        </span>
      </div>
    </div>
  )
}

function SpinnerIcon() {
  return (
    <svg
      className="animate-spin"
      width="12"
      height="12"
      viewBox="0 0 12 12"
      fill="none"
      aria-hidden="true"
    >
      <circle cx="6" cy="6" r="4.5" stroke="currentColor" strokeOpacity="0.25" strokeWidth="1.5" />
      <path
        d="M6 1.5A4.5 4.5 0 0 1 10.5 6"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
    </svg>
  )
}
