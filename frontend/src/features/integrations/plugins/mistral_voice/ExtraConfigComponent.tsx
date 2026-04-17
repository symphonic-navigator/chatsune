import { useCallback, useEffect, useState } from 'react'
import { useSecretsStore } from '../../secretsStore'
import {
  cloneVoice,
  deleteVoice,
  listVoices,
  type MistralVoice,
} from './api'
import { refreshMistralVoices } from './voices'

export function ExtraConfigComponent() {
  const apiKey = useSecretsStore((s) => s.getSecret('mistral_voice', 'api_key'))
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
    if (!apiKey) return
    try {
      setVoices(await listVoices(apiKey))
      await refreshMistralVoices(apiKey)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }, [apiKey])

  useEffect(() => { void refresh() }, [refresh])

  const submitAudio = async (audio: Blob) => {
    if (!apiKey || !name) return
    setBusy(true)
    setError(null)
    try {
      await cloneVoice({ apiKey, audio, name })
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
    if (!apiKey) return
    if (!confirm('Delete this cloned voice?')) return
    try {
      await deleteVoice(apiKey, voiceId)
      await refresh()
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      setError(msg)
    }
  }

  const startRecording = async () => {
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

  if (!apiKey) return null

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
              className="rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs hover:bg-white/[0.06] disabled:opacity-50"
            >
              🎙 Start recording
            </button>
          ) : (
            <div className="flex flex-col gap-1.5">
              <button
                type="button"
                onClick={stopRecording}
                disabled={busy}
                className="rounded-lg border border-red-400/40 bg-red-400/10 px-3 py-2 text-xs hover:bg-red-400/20"
              >
                ⏹ Stop &amp; submit
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

          <label className="cursor-pointer rounded-lg border border-white/10 bg-white/[0.03] px-3 py-2 text-xs hover:bg-white/[0.06] aria-disabled:opacity-50">
            📁 Upload audio
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

