import { useEffect, useRef, useState } from 'react'
import { meApi } from '../../../core/api/meApi'

const MAX_LENGTH = 2000

type SaveStatus = 'idle' | 'saving' | 'saved' | 'error'

export function AboutMeTab() {
  const [text, setText] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState(false)
  const [saveStatus, setSaveStatus] = useState<SaveStatus>('idle')
  const savedTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => {
    return () => {
      if (savedTimerRef.current) clearTimeout(savedTimerRef.current)
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

  const isDirty = text !== original

  if (loading) {
    return (
      <div className="p-6 text-[12px] text-white/30 font-mono tracking-widest uppercase">
        Loading...
      </div>
    )
  }

  if (loadError) {
    return (
      <div className="p-6 text-[12px] text-red-400/70 font-mono">
        Could not load profile — please try again later.
      </div>
    )
  }

  return (
    <div className="p-6 max-w-2xl">
      <label htmlFor="about-me-textarea" className="block text-[10px] uppercase tracking-[0.15em] text-white/50 font-mono mb-2">
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
            <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">
              Saved
            </span>
          )}
          {saveStatus === 'error' && (
            <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">
              Save failed
            </span>
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
  )
}
