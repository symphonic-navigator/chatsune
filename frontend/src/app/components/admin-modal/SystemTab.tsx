import { useEffect, useId, useRef, useState } from "react"
import { settingsApi } from "../../../core/api/settings"

const MAX_LENGTH = 4000

export function SystemTab() {
  const [content, setContent] = useState("")
  const [savedContent, setSavedContent] = useState("")
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [showSaved, setShowSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const dismissTimer = useRef<ReturnType<typeof setTimeout> | null>(null)
  const textareaId = useId()

  const dirty = content !== savedContent

  useEffect(() => {
    async function fetch() {
      setLoading(true)
      setError(null)
      try {
        const data = await settingsApi.getSystemPrompt()
        setContent(data.content)
        setSavedContent(data.content)
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load system prompt")
      } finally {
        setLoading(false)
      }
    }
    fetch()
  }, [])

  useEffect(() => {
    return () => {
      if (dismissTimer.current) clearTimeout(dismissTimer.current)
    }
  }, [])

  async function handleSave() {
    setSaving(true)
    setError(null)
    setShowSaved(false)
    try {
      const data = await settingsApi.setSystemPrompt(content)
      setSavedContent(data.content)
      setShowSaved(true)
      if (dismissTimer.current) clearTimeout(dismissTimer.current)
      dismissTimer.current = setTimeout(() => setShowSaved(false), 2000)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save system prompt")
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="flex flex-1 items-center justify-center">
        <div className="flex items-center gap-3">
          <div className="h-4 w-4 animate-spin rounded-full border-2 border-gold/30 border-t-gold" />
          <span className="text-[12px] text-white/60">Loading system prompt...</span>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-4 p-4 overflow-hidden">
      <div>
        <h3 className="text-[13px] font-medium text-white/80">Global System Prompt</h3>
        <p className="mt-1 text-[11px] text-white/60 leading-relaxed">
          This prompt is prepended to every conversation across all users and personas.
          Use it to set global behavioural guidelines or safety instructions.
        </p>
      </div>

      {error && (
        <div className="rounded-lg border border-red-400/20 bg-red-400/5 px-3 py-2 text-[11px] text-red-400">
          {error}
        </div>
      )}

      <label htmlFor={textareaId} className="sr-only">Global system prompt</label>
      <textarea
        id={textareaId}
        value={content}
        onChange={(e) => {
          if (e.target.value.length <= MAX_LENGTH) {
            setContent(e.target.value)
          }
        }}
        placeholder="Enter a global system prompt..."
        className="flex-1 min-h-[240px] resize-y rounded-lg border border-white/8 bg-surface p-3 text-[12px] text-white/70 font-mono leading-relaxed placeholder:text-white/40 focus:border-white/15 focus:outline-none transition-colors"
      />

      <div className="flex items-center justify-between">
        <span className="text-[11px] text-white/60">
          {content.length} / {MAX_LENGTH}
        </span>

        <div className="flex items-center gap-3">
          {showSaved && (
            <span className="text-[11px] text-gold">Saved</span>
          )}

          <button
            type="button"
            onClick={handleSave}
            disabled={!dirty || saving}
            className="rounded-lg border border-white/8 px-4 py-1.5 text-[11px] text-white/60 transition-colors enabled:hover:bg-white/6 enabled:hover:text-white/80 disabled:opacity-30 disabled:cursor-not-allowed cursor-pointer"
          >
            {saving ? "Saving..." : "Save"}
          </button>
        </div>
      </div>
    </div>
  )
}
