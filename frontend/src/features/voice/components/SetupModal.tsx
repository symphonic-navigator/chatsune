import { useEffect } from 'react'
import { useEngineLoader, type StepStatus } from '../stores/engineLoaderStore'

interface Props {
  onComplete: () => void
  onCancel: () => void
}

function StepIcon({ status }: { status: StepStatus }) {
  if (status === 'loading') {
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
  return (
    <span className="h-3 w-3 rounded-full border border-white/20 flex-shrink-0" />
  )
}

export function SetupModal({ onComplete, onCancel }: Props) {
  const { steps, ready, startLoading } = useEngineLoader()

  // Ensure loading has started (might already be running in background)
  useEffect(() => { startLoading() }, [startLoading])

  // Auto-close when all engines are ready
  useEffect(() => {
    if (ready) onComplete()
  }, [ready, onComplete])

  const errors = steps.filter((s) => s.error)
  const hasError = errors.length > 0

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
      <div className="w-full max-w-md rounded-xl border border-white/10 bg-surface p-6 shadow-2xl">
        <p className="text-[14px] font-semibold text-white/85">Voice Mode Setup</p>
        <p className="mt-1 text-[11px] text-white/45 font-mono">
          {hasError
            ? 'Some models failed to load. Check the error below.'
            : 'Loading AI models for on-device processing. This happens once per session.'}
        </p>

        <ul className="mt-5 space-y-3">
          {steps.map((step) => (
            <li key={step.id} className="flex items-center gap-3">
              <StepIcon status={step.status} />
              <span className={`text-[12px] flex-1 ${step.status === 'done' ? 'text-white/60' : 'text-white/80'}`}>
                {step.label}
              </span>
              <span className="text-[10px] text-white/35 font-mono">{step.size}</span>
            </li>
          ))}
        </ul>

        {errors.length > 0 && (
          <div className="mt-4 rounded-md border border-red-500/20 bg-red-500/5 px-3 py-2">
            {errors.map((e) => (
              <p key={e.id} className="text-[10px] text-red-400 font-mono break-all">{e.error}</p>
            ))}
          </div>
        )}

        <p className="mt-4 text-right text-[10px] text-white/35 font-mono">Total: ~72.5 MB</p>

        <div className="mt-5 flex justify-end">
          <button
            type="button"
            onClick={onCancel}
            className="rounded-md border border-white/10 bg-white/5 px-3 py-1.5 text-[11px] text-white/60 hover:bg-white/10 transition-colors"
          >
            {hasError ? 'Close' : 'Hide'}
          </button>
        </div>
      </div>
    </div>
  )
}
