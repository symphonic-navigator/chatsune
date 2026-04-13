import { useCallback, useEffect, useState } from 'react'
import { modelManager } from '../infrastructure/modelManager'
import { whisperEngine } from '../engines/whisperEngine'
import { kokoroEngine } from '../engines/kokoroEngine'
import { sttRegistry, ttsRegistry } from '../engines/registry'

type StepStatus = 'waiting' | 'downloading' | 'done' | 'error'

interface Step {
  id: string
  label: string
  size: string
}

const STEPS: Step[] = [
  { id: 'whisper-tiny', label: 'Speech Recognition', size: '31 MB' },
  { id: 'silero-vad',   label: 'Voice Detection',    size: '1.5 MB' },
  { id: 'kokoro-tts',   label: 'Speech Synthesis',   size: '40 MB' },
]

interface Props {
  onComplete: () => void
  onCancel: () => void
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'downloading') {
    return (
      <span className="h-3 w-3 animate-spin rounded-full border-2 border-white/20 border-t-gold flex-shrink-0" />
    )
  }
  if (status === 'done') {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
        <path d="M2 6l3 3 5-5" stroke="#22c55e" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }
  if (status === 'error') {
    return (
      <svg width="12" height="12" viewBox="0 0 12 12" fill="none" className="flex-shrink-0">
        <path d="M3 3l6 6M9 3l-6 6" stroke="#ef4444" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }
  // waiting
  return (
    <span className="h-3 w-3 rounded-full border border-white/20 flex-shrink-0" />
  )
}

export function SetupModal({ onComplete, onCancel }: Props) {
  const [statuses, setStatuses] = useState<Record<string, StepStatus>>({
    'whisper-tiny': 'waiting',
    'silero-vad':   'waiting',
    'kokoro-tts':   'waiting',
  })

  const setStatus = useCallback((id: string, status: StepStatus) => {
    setStatuses((prev) => ({ ...prev, [id]: status }))
  }, [])

  useEffect(() => {
    let cancelled = false
    const device = modelManager.detectDevice()

    async function run() {
      // Step 1: Whisper
      setStatus('whisper-tiny', 'downloading')
      try {
        await whisperEngine.init(device)
        if (cancelled) return
        sttRegistry.register(whisperEngine)
        await sttRegistry.setActive(whisperEngine.id)
        setStatus('whisper-tiny', 'done')
      } catch {
        if (!cancelled) setStatus('whisper-tiny', 'error')
        return
      }

      // Step 2: VAD — no separate engine, just mark downloaded
      setStatus('silero-vad', 'downloading')
      try {
        // VAD is initialised lazily inside the pipeline; mark it as ready here
        await modelManager.markDownloaded('silero-vad')
        if (cancelled) return
        setStatus('silero-vad', 'done')
      } catch {
        if (!cancelled) setStatus('silero-vad', 'error')
        return
      }

      // Step 3: Kokoro
      setStatus('kokoro-tts', 'downloading')
      try {
        await kokoroEngine.init(device)
        if (cancelled) return
        ttsRegistry.register(kokoroEngine)
        await ttsRegistry.setActive(kokoroEngine.id)
        setStatus('kokoro-tts', 'done')
      } catch {
        if (!cancelled) setStatus('kokoro-tts', 'error')
        return
      }

      if (!cancelled) onComplete()
    }

    run()

    return () => { cancelled = true }
  }, [onComplete, setStatus])

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-xl border border-white/10 bg-surface p-6 shadow-2xl">
        {/* Header */}
        <p className="text-[14px] font-semibold text-white/85">Voice Mode Setup</p>
        <p className="mt-1 text-[11px] text-white/45 font-mono">
          Downloading AI models for on-device processing. This happens once and may take a few minutes.
        </p>

        {/* Steps */}
        <ul className="mt-5 space-y-3">
          {STEPS.map((step) => {
            const status = statuses[step.id]
            const isDone = status === 'done'
            return (
              <li key={step.id} className="flex items-center gap-3">
                <StepIcon status={status} />
                <span
                  className={
                    isDone
                      ? 'text-[12px] text-white/60 flex-1'
                      : 'text-[12px] text-white/80 flex-1'
                  }
                >
                  {step.label}
                </span>
                <span className="text-[10px] text-white/35 font-mono">{step.size}</span>
              </li>
            )
          })}
        </ul>

        {/* Total */}
        <p className="mt-4 text-right text-[10px] text-white/35 font-mono">Total: ~72.5 MB</p>

        {/* Actions */}
        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white/60 hover:bg-white/10 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
