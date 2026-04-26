import { useState, useEffect } from 'react'
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

  // Track the last applied state so we can disable "Apply" when nothing changed.
  const [appliedKey, setAppliedKey] = useState<string>('')

  // Test-image state
  const [testing, setTesting] = useState(false)
  const [testImages, setTestImages] = useState<string[]>([])
  const [testError, setTestError] = useState<string | null>(null)

  // Apply state
  const [applying, setApplying] = useState(false)

  const applyConfig = useImagesStore((s) => s.applyConfig)

  // Hydrate from the active config or fall back to the first available connection.
  useEffect(() => {
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
      setAppliedKey(JSON.stringify({ connection_id: active.connection_id, group_id: active.group_id, config: active.config }))
    } else {
      const first = available[0]
      const firstGroup = first.group_ids[0] ?? 'xai_imagine'
      setConnectionId(first.connection_id)
      setGroupId(firstGroup)
      setConfig(defaultConfigForGroup(firstGroup))
      setAppliedKey('')
    }
  }, [available, active])

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

  const currentKey = JSON.stringify({ connection_id: connectionId, group_id: groupId, config })
  const hasChanges = currentKey !== appliedKey

  const handleApply = async () => {
    setApplying(true)
    try {
      await applyConfig({ connection_id: connectionId, group_id: groupId, config })
      setAppliedKey(currentKey)
    } catch (err) {
      console.error('[images] Apply config failed:', err)
    } finally {
      setApplying(false)
    }
  }

  const handleTest = async () => {
    setTesting(true)
    setTestImages([])
    setTestError(null)
    try {
      const result = await imagesApi.testImagine(connectionId, {
        group_id: groupId,
        config,
        prompt: 'A beautiful golden sunset over calm ocean waves',
      })
      const urls: string[] = []
      for (const item of result.items) {
        if (item.kind === 'image') {
          // The blob_url field on a GeneratedImageResult — but the test endpoint
          // returns ImageGenItem which only carries an id, not a URL. Use the
          // /api/images/{id}/blob path to display. For now surface what we have.
          urls.push(`/api/images/${item.id}`)
        }
      }
      if (urls.length === 0) {
        setTestError('Generation completed but all results were moderated.')
      } else {
        setTestImages(urls)
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

      {/* Action row */}
      <div className="flex gap-2">
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
        <button
          type="button"
          onClick={() => { void handleApply() }}
          disabled={!hasChanges || applying}
          className={[
            'flex-1 text-[11px] px-2 py-1.5 rounded border transition',
            hasChanges && !applying
              ? 'border-[#c084fc]/50 bg-[#c084fc]/15 text-[#c084fc] hover:bg-[#c084fc]/25'
              : 'border-white/10 bg-white/5 text-white/30 cursor-not-allowed',
          ].join(' ')}
        >
          {applying ? 'Applying…' : 'Apply'}
        </button>
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
