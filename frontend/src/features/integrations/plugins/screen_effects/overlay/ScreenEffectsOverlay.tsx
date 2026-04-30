import { useEffect, useState } from 'react'
import { eventBus } from '../../../../../core/websocket/eventBus'
import { Topics } from '../../../../../core/types/events'
import type { IntegrationInlineTrigger } from '../../../types'
import { RisingEmojisEffect } from './RisingEmojisEffect'

type ActiveEffect = {
  id: string
  kind: 'rising_emojis'
  emojis: string[]
  reduced: boolean
}

/**
 * Globally-mounted overlay that subscribes to INTEGRATION_INLINE_TRIGGER
 * events for the screen_effect integration and renders one short-lived
 * effect component per trigger. Effects overlap freely; each removes
 * itself from the active list via its own onDone callback.
 */
export function ScreenEffectsOverlay() {
  const [active, setActive] = useState<ActiveEffect[]>([])

  useEffect(() => {
    const reduced = window.matchMedia(
      '(prefers-reduced-motion: reduce)',
    ).matches
    return eventBus.on(Topics.INTEGRATION_INLINE_TRIGGER, (event) => {
      const trigger = event.payload as unknown as IntegrationInlineTrigger
      if (trigger.integration_id !== 'screen_effect') return
      const payload = trigger.payload as
        | { effect?: string; emojis?: string[] }
        | undefined
      if (!payload || payload.effect !== 'rising_emojis') return
      const id = crypto.randomUUID()
      setActive((prev) => [
        ...prev,
        {
          id,
          kind: 'rising_emojis',
          emojis: payload.emojis ?? ['✨'],
          reduced,
        },
      ])
    })
  }, [])

  const remove = (id: string) =>
    setActive((prev) => prev.filter((e) => e.id !== id))

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        pointerEvents: 'none',
        zIndex: 90,
        overflow: 'hidden',
      }}
      aria-hidden="true"
      data-testid="screen-effects-overlay"
    >
      {active.map((e) =>
        e.kind === 'rising_emojis' ? (
          <RisingEmojisEffect
            key={e.id}
            emojis={e.emojis}
            reduced={e.reduced}
            onDone={() => remove(e.id)}
          />
        ) : null,
      )}
    </div>
  )
}
