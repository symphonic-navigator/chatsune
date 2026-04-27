import { useEffect, useRef } from 'react'
import { audioPlayback } from './audioPlayback'
import { useIsReadingAloud } from '../components/ReadAloudButton'
import {
  getActiveGroup,
  subscribeActiveGroup,
} from '../../chat/responseTaskGroup'
import { useConversationModeStore } from '../stores/conversationModeStore'
import { useCockpitStore } from '../../chat/cockpit/cockpitStore'
import { computeTtsExpected } from './ttsExpected'

interface UseTtsExpectedOptions {
  /**
   * Fires once each time the predicate transitions false → true.
   * Visualiser uses this to restart its RAF loop after a fade-out.
   */
  onTrueEdge?: () => void
}

interface TtsExpectedAccessor {
  /** Read the current predicate value. Cheap; no React renders triggered. */
  (): boolean
}

/**
 * Composes audioPlayback, useIsReadingAloud, the active Group registry,
 * conversationModeStore, and cockpitStore into a single "TTS expected"
 * boolean. Returns a stable getter so consumers can read it inside a
 * RAF loop without forcing per-frame React renders.
 */
export function useTtsExpected(
  options: UseTtsExpectedOptions = {},
): TtsExpectedAccessor {
  // useIsReadingAloud is itself a hook with its own subscription, so we
  // call it here and keep the latest value in a ref. This is the only
  // value we cannot read on-demand from a store getter.
  const isReadingAloud = useIsReadingAloud()
  const isReadingAloudRef = useRef(isReadingAloud)
  isReadingAloudRef.current = isReadingAloud

  const onTrueEdgeRef = useRef(options.onTrueEdge)
  onTrueEdgeRef.current = options.onTrueEdge

  // Cached previous predicate value, for edge detection.
  const lastValueRef = useRef(false)

  const accessorRef = useRef<TtsExpectedAccessor | null>(null)
  if (accessorRef.current === null) {
    const accessor: TtsExpectedAccessor = () => {
      const group = getActiveGroup()
      const cockpit = useCockpitStore.getState()
      const autoRead = group !== null
        ? cockpit.bySession[group.sessionId]?.autoRead === true
        : false
      return computeTtsExpected({
        audioActive: audioPlayback.isActive(),
        isReadingAloud: isReadingAloudRef.current,
        hasActiveGroup: group !== null,
        liveModeActive: useConversationModeStore.getState().active,
        autoReadEnabledForActiveGroup: autoRead,
      })
    }
    accessorRef.current = accessor
  }

  // Edge detection: re-evaluate the predicate whenever any subscribed
  // source changes, and fire onTrueEdge on the false→true transition.
  useEffect(() => {
    const evaluate = () => {
      const value = accessorRef.current!()
      if (value && !lastValueRef.current && onTrueEdgeRef.current) {
        onTrueEdgeRef.current()
      }
      lastValueRef.current = value
    }

    // Sources to subscribe to.
    const unsubAudio = audioPlayback.subscribe(evaluate)
    const unsubGroup = subscribeActiveGroup(evaluate)
    const unsubMode = useConversationModeStore.subscribe(evaluate)
    const unsubCockpit = useCockpitStore.subscribe(evaluate)

    // Initial evaluation so lastValueRef seeds correctly.
    evaluate()

    return () => {
      unsubAudio()
      unsubGroup()
      unsubMode()
      unsubCockpit()
    }
  }, [])

  // Re-evaluate when isReadingAloud (the one React-driven source) changes.
  useEffect(() => {
    const value = accessorRef.current!()
    if (value && !lastValueRef.current && onTrueEdgeRef.current) {
      onTrueEdgeRef.current()
    }
    lastValueRef.current = value
  }, [isReadingAloud])

  return accessorRef.current
}
