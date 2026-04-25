import { useState } from "react"
import { normalisePhrase } from "./normalisePhrase"

interface Props {
  value: string[]
  onChange: (next: string[]) => void
  disabled?: boolean
}

export function TriggerPhraseEditor({ value, onChange, disabled }: Props) {
  const [input, setInput] = useState("")
  const preview = normalisePhrase(input)

  const addPhrase = () => {
    if (!preview) return
    if (value.includes(preview)) {
      // Normalised duplicate — emit unchanged for parent to update field state
      onChange(value)
      setInput("")
      return
    }
    onChange([...value, preview])
    setInput("")
  }

  const removePhrase = (idx: number) => {
    const next = value.filter((_, i) => i !== idx)
    onChange(next)
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2">
        {value.map((phrase, i) => (
          <span
            key={`${phrase}-${i}`}
            className="inline-flex items-center gap-1 rounded-full bg-white/5 px-3 py-1 text-sm"
          >
            <span className="font-mono">{phrase}</span>
            <button
              type="button"
              aria-label={`Remove ${phrase}`}
              onClick={() => removePhrase(i)}
              disabled={disabled}
              className="opacity-60 hover:opacity-100"
            >
              ×
            </button>
          </span>
        ))}
      </div>
      <div>
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault()
              addPhrase()
            }
          }}
          disabled={disabled}
          placeholder="add phrase…"
          className="w-full rounded border border-white/10 bg-transparent px-3 py-2 text-sm"
        />
        {input.trim() !== "" && preview !== input && (
          <p className="mt-1 text-xs text-white/50">
            Will be saved as: <span className="font-mono">{preview}</span>
          </p>
        )}
      </div>
      <p className="text-xs text-white/40">
        Add words or short phrases that should trigger this document. International
        characters and emoji are supported. Choose phrases specific enough not to
        match accidentally inside other words.
      </p>
    </div>
  )
}
