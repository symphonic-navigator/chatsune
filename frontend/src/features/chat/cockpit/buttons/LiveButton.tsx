import { useEffect, useRef } from 'react'
import { CockpitButton } from '../CockpitButton'
import { useCockpitSession, useCockpitStore } from '../cockpitStore'
import { useConversationModeStore } from '@/features/voice/stores/conversationModeStore'
import { stopActiveReadAloud } from '@/features/voice/components/ReadAloudButton'
import { micActivity } from '@/features/voice/infrastructure/micActivity'

type Props = {
  sessionId: string
  canEnterLive: boolean
  disabledReason: 'no-voice' | 'not-allowed' | null
}

export function LiveButton({ sessionId, canEnterLive, disabledReason }: Props) {
  const active = useConversationModeStore((s) => s.active)
  const enter = useConversationModeStore((s) => s.enter)
  const exit = useConversationModeStore((s) => s.exit)
  const cockpit = useCockpitSession(sessionId)
  const setAutoRead = useCockpitStore((s) => s.setAutoRead)
  const clearAutoReadRequest = useCockpitStore((s) => s.clearAutoReadRequest)

  const micMuted = useConversationModeStore((s) => s.micMuted)
  const buttonRef = useRef<HTMLButtonElement>(null)
  const pulseRef = useRef(0)
  const rafRef = useRef<number | null>(null)
  const reducedMotionRef = useRef(false)

  useEffect(() => {
    const mq = window.matchMedia('(prefers-reduced-motion: reduce)')
    reducedMotionRef.current = mq.matches
    const listener = () => { reducedMotionRef.current = mq.matches }
    mq.addEventListener('change', listener)
    return () => mq.removeEventListener('change', listener)
  }, [])

  useEffect(() => {
    const enabled = active && !micMuted && !reducedMotionRef.current
    if (!enabled) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      pulseRef.current = 0
      const el = buttonRef.current
      if (el) {
        el.style.transform = ''
        el.style.boxShadow = ''
        el.style.transition = ''
      }
      return
    }

    const tick = () => {
      const level = micActivity.getLevel()
      const vad = micActivity.getVadActive()
      const target = vad
        ? Math.min(1, level * 2.5)
        : Math.min(0.4, level * 1.5)
      pulseRef.current += (target - pulseRef.current) * 0.18

      const el = buttonRef.current
      if (el) {
        const p = pulseRef.current
        el.style.transform = `scale(${(1 + p * 0.12).toFixed(3)})`
        el.style.boxShadow = `0 0 ${(p * 18).toFixed(2)}px rgba(74, 222, 128, ${(p * 0.6).toFixed(3)})`
        el.style.transition = 'transform 60ms linear, box-shadow 60ms linear'
      }
      rafRef.current = requestAnimationFrame(tick)
    }
    rafRef.current = requestAnimationFrame(tick)

    return () => {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current)
        rafRef.current = null
      }
      const el = buttonRef.current
      if (el) {
        el.style.transform = ''
        el.style.boxShadow = ''
        el.style.transition = ''
      }
    }
  }, [active, micMuted])

  if (!canEnterLive) {
    return (
      <CockpitButton
        icon="🎙"
        state="disabled"
        accent="green"
        label="Live mode unavailable"
        panel={
          <p className="text-white/70">
            {disabledReason === 'no-voice'
              ? 'Live mode needs TTS and STT on the persona.'
              : 'Live mode is not enabled for your account.'}
          </p>
        }
      />
    )
  }

  const handleClick = () => {
    if (active) {
      exit()
      return
    }
    // Entering Live mode: silence and disarm the Read-Aloud pipeline so it
    // does not race the live ResponseTaskGroup for audio output.
    if (cockpit?.autoRead) {
      void setAutoRead(sessionId, false)
    }
    clearAutoReadRequest()
    stopActiveReadAloud()
    enter()
  }

  return (
    <CockpitButton
      icon="🎙"
      state={active ? 'active' : 'idle'}
      accent="green"
      label={active ? 'Voice chat · on' : 'Voice chat · off'}
      onClick={handleClick}
      buttonRef={buttonRef}
      panel={
        <div className="text-white/80">
          <div className="font-semibold text-[#4ade80] mb-1">Voice chat</div>
          <p className="text-xs leading-relaxed">
            Hands-free conversation. The mic stays open, the assistant speaks answers
            aloud. You can interrupt by clicking the voice button. Best for long sessions.
          </p>
        </div>
      }
    />
  )
}
