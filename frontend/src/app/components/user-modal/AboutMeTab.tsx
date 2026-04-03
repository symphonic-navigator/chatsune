import { useEffect, useRef, useState } from 'react'
import { meApi } from '../../../core/api/meApi'
import { useAuthStore } from '../../../core/store/authStore'

const MAX_LENGTH = 2000
const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

export function AboutMeTab() {
  const user = useAuthStore((s) => s.user)

  // --- Display Name ---
  const [displayName, setDisplayName] = useState(user?.display_name ?? '')
  const [dnOriginal, setDnOriginal] = useState(user?.display_name ?? '')
  const [dnStatus, setDnStatus] = useState<SaveStatus>('idle')
  const dnTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // --- About Me text ---
  const [text, setText] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
    }
  }, [])

  useEffect(() => {
    meApi.getAboutMe()
      .then((data) => {
        const value = data.about_me ?? ''
        setText(value)
        setOriginal(value)
      })
      .catch(() => setLoadError(true))
      .finally(() => setLoading(false))
  }, [])

  async function handleSaveDisplayName() {
    setDnStatus('saving')
    try {
      const updated = await meApi.updateDisplayName(displayName)
      setDnOriginal(updated.display_name)
      setDisplayName(updated.display_name)
      setDnStatus('saved')
      if (dnTimerRef.current) clearTimeout(dnTimerRef.current)
      dnTimerRef.current = setTimeout(() => setDnStatus('idle'), 2000)
    } catch {
      setDnStatus('error')
    }
  }

  async function handleSave() {
    setSaveStatus('saving')
    try {
      const data = await meApi.updateAboutMe(text || null)
      const value = data.about_me ?? ''
      setText(value)
      setOriginal(value)
      setSaveStatus('saved')
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
      savedTimerRef.current = setTimeout(() => setSaveStatus('idle'), 2000)
    } catch {
      setSaveStatus('error')
    }
  }

  const isDnDirty = displayName !== dnOriginal
  const isDirty = text !== original

  return (
    <div className="p-6 max-w-2xl flex flex-col gap-8">

      {/* Display Name */}
      <div>
        <label
          htmlFor="display-name-input"
          className={LABEL}
        >
          Display Name
        </label>
        <div className="flex items-center gap-3">
          <input
            id="display-name-input"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            maxLength={64}
            placeholder="Unnamed User"
            className="flex-1 bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors"
          />
          <div className="flex items-center gap-2">
            {dnStatus === 'saved' && (
              <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
            )}
            {dnStatus === 'error' && (
              <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Failed</span>
            )}
            <button
              type="button"
              aria-label="Save display name"
              onClick={handleSaveDisplayName}
              disabled={dnStatus === 'saving' || !isDnDirty}
              className={[
                'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                isDnDirty
                  ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                  : 'bg-transparent text-white/25 cursor-default',
              ].join(' ')}
            >
              {dnStatus === 'saving' ? 'Saving...' : 'Save'}
            </button>
          </div>
        </div>
      </div>

      {/* About Me text */}
      {loading ? (
        <div className="text-[12px] text-white/30 font-mono tracking-widest uppercase">Loading...</div>
      ) : loadError ? (
        <div className="text-[12px] text-red-400/70 font-mono">
          Could not load profile — please try again later.
        </div>
      ) : (
        <div>
          <label htmlFor="about-me-textarea" className={LABEL}>
            About You
          </label>
          <p className="text-[12px] text-white/40 font-mono mb-4 leading-relaxed">
            Tell your personas about yourself — your name, interests, preferences. Included at low
            priority in every conversation.
          </p>
          <textarea
            id="about-me-textarea"
            value={text}
            onChange={(e) => {
              if (e.target.value.length <= MAX_LENGTH) setText(e.target.value)
            }}
            placeholder="e.g. My name is Chris, I'm a developer living in Vienna..."
            className="w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-3 text-white/75 font-mono text-[13px] leading-relaxed outline-none focus:border-gold/30 transition-colors resize-y"
            style={{ minHeight: 160 }}
          />
          <div className="flex items-center justify-between mt-3">
            <span className="font-mono text-[10px] text-white/25 tracking-wider">
              {text.length} / {MAX_LENGTH}
            </span>
            <div className="flex items-center gap-3">
              {saveStatus === 'saved' && (
                <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">Saved</span>
              )}
              {saveStatus === 'error' && (
                <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">Save failed</span>
              )}
              <button
                type="button"
                onClick={handleSave}
                disabled={saveStatus === 'saving' || !isDirty}
                className={[
                  'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
                  isDirty
                    ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                    : 'bg-transparent text-white/25 cursor-default',
                ].join(' ')}
              >
                {saveStatus === 'saving' ? 'Saving...' : 'Save'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
