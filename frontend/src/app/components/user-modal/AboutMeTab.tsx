import { useEffect, useState } from 'react'
import { meApi } from '../../../core/api/meApi'

const MAX_LENGTH = 2000

export function AboutMeTab() {
  const [text, setText] = useState('')
  const [original, setOriginal] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [saveError, setSaveError] = useState(false)

  useEffect(() => {
    meApi.getAboutMe()
      .then((data) => {
        const value = data.about_me ?? ''
        setText(value)
        setOriginal(value)
      })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [])

  async function handleSave() {
    setSaving(true)
    setSaved(false)
    setSaveError(false)
    try {
      const data = await meApi.updateAboutMe(text || null)
      const value = data.about_me ?? ''
      setText(value)
      setOriginal(value)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch {
      setSaveError(true)
    } finally {
      setSaving(false)
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

  return (
    <div className="p-6 max-w-2xl">
      <label className="block text-[10px] uppercase tracking-[0.15em] text-white/50 font-mono mb-2">
        About You
      </label>
      <p className="text-[12px] text-white/40 font-mono mb-4 leading-relaxed">
        Tell your personas about yourself — your name, interests, preferences. Included at low
        priority in every conversation.
      </p>
      <textarea
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
          {saved && (
            <span className="font-mono text-[10px] text-white/40 tracking-wider uppercase">
              Saved
            </span>
          )}
          {saveError && (
            <span className="font-mono text-[10px] text-red-400/80 tracking-wider uppercase">
              Save failed
            </span>
          )}
          <button
            type="button"
            onClick={handleSave}
            disabled={saving || !isDirty}
            className={[
              'font-mono text-[11px] uppercase tracking-[0.12em] px-5 py-2 rounded-lg transition-all border border-white/10',
              isDirty
                ? 'bg-white/8 text-white/80 hover:bg-white/12 cursor-pointer'
                : 'bg-transparent text-white/25 cursor-default',
            ].join(' ')}
          >
            {saving ? 'Saving...' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
