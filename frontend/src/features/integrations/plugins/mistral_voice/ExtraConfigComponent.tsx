import { useCallback, useEffect, useState } from 'react'
import {
  cloneVoice,
  deleteVoice,
  listVoices,
  type MistralVoice,
} from './api'
import { refreshMistralVoices } from './voices'
import { useIntegrationsStore } from '../../store'

const INTEGRATION_ID = 'mistral_voice'

const MIC_ICON = (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="5.5" y="2" width="3" height="7" rx="1.5" stroke="currentColor" strokeWidth="1.2" />
    <path d="M3 7.5C3 9.985 4.765 12 7 12M7 12C9.235 12 11 9.985 11 7.5M7 12V14" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
  </svg>
)

const STOP_ICON = (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <rect x="3" y="3" width="8" height="8" rx="1" fill="currentColor" />
  </svg>
)

const UPLOAD_ICON = (
  <svg width="14" height="14" viewBox="0 0 14 14" fill="none" aria-hidden="true">
    <path d="M2 10V11.5C2 12.05 2.45 12.5 3 12.5H11C11.55 12.5 12 12.05 12 11.5V10" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" />
    <path d="M7 2V9M7 2L4.5 4.5M7 2L9.5 4.5" stroke="currentColor" strokeWidth="1.2" strokeLinecap="round" strokeLinejoin="round" />
  </svg>
)

export function ExtraConfigComponent() {
  // The integration must be enabled (and therefore linked to a Premium
  // Provider Account with a Mistral API key) for clone/list/delete to work.
  // The API key itself now lives server-side — we no longer check a client
  // secrets store.
  const enabled = useIntegrationsStore(
    (s) => s.configs?.[INTEGRATION_ID]?.effective_enabled === true,
  )
  const [voices, setVoices] = useState<MistralVoice[]>([])
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Raw MediaRecorder-based recording — audioCapture uses VAD/PTT for chat,
  // but here we need a simple manual start/stop for voice sample capture.
  const [recorder, setRecorder] = useState<MediaRecorder | null>(null)
  const [seconds, setSeconds] = useState(0)

  useEffect(() => {
    if (!recorder) { setSeconds(0); return }
    const interval = setInterval(() => setSeconds((s) => s + 1), 1000)
    return () => clearInterval(interval)
  }, [recorder])

  const refresh = useCallback(async () => {
    if (!enabled) return
    setError(null)
    try {
      setVoices(await listVoices())
      await refreshMistralVoices()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }, [enabled])

  useEffect(() => { void refresh() }, [refresh])

  const submitAudio = async (audio: Blob) => {
    if (!enabled || !name) return
    setBusy(true)
    setError(null)
    try {
      await cloneVoice({ audio, name })
      setName('')
      await refresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    } finally {
      setBusy(false)
    }
  }

  const handleRemove = async (voiceId: string) => {
    if (!enabled) return
    if (!confirm('Delete this cloned voice?')) return
    setError(null)
    try {
      await deleteVoice(voiceId)
      await refresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }

  const startRecording = async () => {
    setError(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
      const mr = new MediaRecorder(stream)
      const chunks: Blob[] = []
      mr.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data) }
      mr.onstop = async () => {
        stream.getTracks().forEach((t) => t.stop())
        const blob = new Blob(chunks, { type: 'audio/webm' })
        await submitAudio(blob)
      }
      setRecorder(mr)
      mr.start()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }

  const stopRecording = () => {
    recorder?.stop()
    setRecorder(null)
  }

  if (!enabled) return null

  return (
    <section className="mt-4 space-y-3 rounded-lg border border-white/10 bg-white/[0.03] p-4">
      <h4 className="text-sm font-medium">Your cloned voices</h4>
      {voices.length === 0 && <p className="text-xs text-white/50">None yet.</p>}
      <ul className="space-y-1 max-h-48 overflow-y-auto pr-1">
        {voices.map((v) => (
          <li key={v.id} className="flex items-center justify-between text-sm">
            <span>{v.name}</span>
            <button
              type="button"
              onClick={() => void handleRemove(v.id)}
              className="text-xs text-red-400 hover:text-red-300"
            >
              Delete
            </button>
          </li>
        ))}
      </ul>

      <div className="border-t border-white/10 pt-3">
        <h4 className="text-sm font-medium">Clone a new voice</h4>
        <input
          type="text"
          placeholder="Voice name"
          value={name}
          onChange={(e) => setName(e.target.value)}
          disabled={busy}
          className="mt-2 w-full rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-sm focus:border-gold/30 focus:outline-none"
        />

        <div className="mt-3 flex items-center gap-3">
          {!recorder ? (
            <button
              type="button"
              onClick={() => void startRecording()}
              disabled={!name || busy}
              className="flex items-center gap-1.5 rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs hover:bg-white/[0.06] disabled:opacity-50"
            >
              {MIC_ICON} Start recording
            </button>
          ) : (
            <div className="flex flex-col gap-1.5">
              <button
                type="button"
                onClick={stopRecording}
                disabled={busy}
                className="flex items-center gap-1.5 rounded-lg border border-red-400/40 bg-red-400/10 px-3 py-2 text-xs hover:bg-red-400/20"
              >
                {STOP_ICON} Stop &amp; submit
              </button>
              {(() => {
                const mm = Math.floor(seconds / 60).toString()
                const ss = (seconds % 60).toString().padStart(2, '0')
                const reachedRecommended = seconds >= 30
                return (
                  <span
                    className={`text-[11px] font-mono ${reachedRecommended ? 'text-emerald-400' : 'text-white/60'}`}
                  >
                    {reachedRecommended
                      ? `Recommended length reached (${mm}:${ss})`
                      : `Recording: ${mm}:${ss} — recommended 30s`}
                  </span>
                )
              })()}
            </div>
          )}

          <label className="flex items-center gap-1.5 cursor-pointer rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs hover:bg-white/[0.06] aria-disabled:opacity-50">
            {UPLOAD_ICON} Upload audio
            <input
              type="file"
              accept="audio/*"
              disabled={!name || busy}
              className="hidden"
              onChange={async (e) => {
                const file = e.target.files?.[0]
                if (file) await submitAudio(file)
              }}
            />
          </label>
        </div>

        {error && <p className="mt-2 text-xs text-red-400">{error}</p>}
      </div>
    </section>
  )
}
