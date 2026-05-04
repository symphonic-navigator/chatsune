import { useEffect, useRef, useState } from 'react'
import { SECRET_INPUT_STYLE, SECRET_INPUT_NO_AUTOFILL } from '../../../core/utils/secretInputStyle'

// ─── Style constants (opulent prototype palette) ──────────────────────────────

const LABEL = 'block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-1.5 font-mono'
const INPUT =
  'w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors placeholder:text-white/25'
const TEXTAREA =
  'w-full bg-white/[0.03] border border-white/10 rounded-lg px-4 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors placeholder:text-white/25 resize-y min-h-[80px]'
const SELECT =
  'w-full bg-white/[0.03] border border-white/10 rounded-lg px-3 py-2 text-white/75 font-mono text-[13px] outline-none focus:border-gold/30 transition-colors'
const DESCRIPTION = 'mt-1 text-[11px] text-white/35 font-mono'
const SECRET_HINT = 'mt-1 text-[11px] text-white/35 font-mono italic'
const SUBMIT_BASE =
  'mt-2 px-5 py-2 rounded-lg font-mono text-[11px] uppercase tracking-wider transition-all border border-white/20 bg-white/5 text-white/60 hover:bg-white/10 hover:text-white/85 cursor-pointer disabled:opacity-40 disabled:cursor-not-allowed'
const OPTION_STYLE: React.CSSProperties = {
  background: '#0f0d16',
  color: 'rgba(255,255,255,0.85)',
}

// ─── Types ────────────────────────────────────────────────────────────────────

type FieldDef = {
  key: string
  label: string
  field_type: 'text' | 'password' | 'number' | 'boolean' | 'select' | 'textarea'
  required?: boolean
  description?: string
  placeholder?: string
  secret?: boolean
  options?: Array<{ value: string | null; label: string }>
  options_source?: 'plugin'
}

type OptionsProvider = (
  fieldKey: string,
) => Array<{ value: string | null; label: string }> | Promise<Array<{ value: string | null; label: string }>>

interface Props {
  fields: FieldDef[]
  initialValues: Record<string, unknown>
  onSubmit(values: Record<string, string>): void | Promise<void>
  optionsProvider?: OptionsProvider
  submitLabel?: string
  /**
   * When true, the form auto-submits on every field change and does not
   * render a submit button. Use for single-field config like a voice picker.
   */
  autoSubmit?: boolean
}

// ─── Helpers ──────────────────────────────────────────────────────────────────

function isSecretSet(value: unknown): boolean {
  return (
    typeof value === 'object' &&
    value !== null &&
    'is_set' in (value as object) &&
    Boolean((value as { is_set?: boolean }).is_set)
  )
}

// ─── Component ────────────────────────────────────────────────────────────────

export function GenericConfigForm({
  fields,
  initialValues,
  onSubmit,
  optionsProvider,
  submitLabel = 'Save',
  autoSubmit = false,
}: Props) {
  const [values, setValues] = useState<Record<string, string>>(() => {
    const seed: Record<string, string> = {}
    for (const f of fields) {
      const iv = initialValues[f.key]
      seed[f.key] = typeof iv === 'string' ? iv : ''
    }
    return seed
  })
  const [submitting, setSubmitting] = useState(false)
  const submitTimer = useRef<ReturnType<typeof setTimeout> | null>(null)

  useEffect(() => () => {
    if (submitTimer.current !== null) clearTimeout(submitTimer.current)
  }, [])

  // Debounced so rapid edits (typing an API key, tabbing through fields)
  // collapse into a single round-trip. Select changes still feel instant.
  const submitLater = (nextValues: Record<string, string>) => {
    if (!autoSubmit) return
    if (submitTimer.current !== null) clearTimeout(submitTimer.current)
    submitTimer.current = setTimeout(() => {
      submitTimer.current = null
      const payload: Record<string, string> = {}
      for (const f of fields) {
        // Omit secret fields the user left blank (keep existing server-side value).
        if (f.secret && nextValues[f.key] === '') continue
        payload[f.key] = nextValues[f.key]
      }
      setSubmitting(true)
      Promise.resolve(onSubmit(payload)).finally(() => setSubmitting(false))
    }, 400)
  }

  return (
    <form
      className="flex flex-col gap-4"
      onSubmit={async (e) => {
        e.preventDefault()
        setSubmitting(true)
        try {
          const payload: Record<string, string> = {}
          for (const f of fields) {
            // Omit secret fields the user left blank (keep existing server-side value).
            if (f.secret && values[f.key] === '') continue
            payload[f.key] = values[f.key]
          }
          await onSubmit(payload)
        } finally {
          setSubmitting(false)
        }
      }}
    >
      {fields.map((f) => (
        <FieldRow
          key={f.key}
          field={f}
          value={values[f.key]}
          onChange={(v) => {
            const next = { ...values, [f.key]: v }
            setValues(next)
            submitLater(next)
          }}
          secretSet={isSecretSet(initialValues[f.key])}
          optionsProvider={optionsProvider}
        />
      ))}
      {!autoSubmit && (
        <div>
          <button type="submit" disabled={submitting} className={SUBMIT_BASE}>
            {submitting ? 'Saving…' : submitLabel}
          </button>
        </div>
      )}
    </form>
  )
}

// ─── Field rows ───────────────────────────────────────────────────────────────

function FieldRow({
  field,
  value,
  onChange,
  secretSet,
  optionsProvider,
}: {
  field: FieldDef
  value: string
  onChange(v: string): void
  secretSet: boolean
  optionsProvider?: OptionsProvider
}) {
  const labelEl = (
    <label className={LABEL}>
      {field.label}
      {field.required ? ' *' : ''}
    </label>
  )

  if (field.field_type === 'password' || field.secret) {
    return (
      <div>
        {labelEl}
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder={
            secretSet && !value
              ? '••••••••  (set — leave blank to keep)'
              : field.placeholder
          }
          style={SECRET_INPUT_STYLE}
          {...SECRET_INPUT_NO_AUTOFILL}
          className={INPUT}
        />
        {secretSet && !value && (
          <p className={SECRET_HINT}>Currently configured. Type a new value to replace.</p>
        )}
        {field.description && <p className={DESCRIPTION}>{field.description}</p>}
      </div>
    )
  }

  if (field.field_type === 'boolean') {
    return (
      <div>
        <label className="flex items-center gap-2.5 cursor-pointer">
          <input
            type="checkbox"
            checked={value === 'true'}
            onChange={(e) => onChange(e.target.checked ? 'true' : 'false')}
            className="w-4 h-4 accent-gold rounded"
          />
          <span className="text-[13px] font-mono text-white/75">{field.label}{field.required ? ' *' : ''}</span>
        </label>
        {field.description && <p className={DESCRIPTION}>{field.description}</p>}
      </div>
    )
  }

  if (field.field_type === 'select') {
    return (
      <SelectField
        field={field}
        value={value}
        onChange={onChange}
        optionsProvider={optionsProvider}
      />
    )
  }

  if (field.field_type === 'textarea') {
    return (
      <div>
        {labelEl}
        <textarea
          value={value}
          placeholder={field.placeholder}
          onChange={(e) => onChange(e.target.value)}
          className={TEXTAREA}
        />
        {field.description && <p className={DESCRIPTION}>{field.description}</p>}
      </div>
    )
  }

  return (
    <div>
      {labelEl}
      <input
        type={field.field_type === 'number' ? 'number' : 'text'}
        value={value}
        placeholder={field.placeholder}
        onChange={(e) => onChange(e.target.value)}
        className={INPUT}
      />
      {field.description && <p className={DESCRIPTION}>{field.description}</p>}
    </div>
  )
}

function SelectField({
  field,
  value,
  onChange,
  optionsProvider,
}: {
  field: FieldDef
  value: string
  onChange(v: string): void
  optionsProvider?: OptionsProvider
}) {
  const [options, setOptions] = useState<Array<{ value: string | null; label: string }>>(
    field.options ?? [],
  )

  useEffect(() => {
    // Dynamic options: provider takes precedence over whatever static
    // `options` the field carries. Empty arrays are still arrays, so the
    // previous truthiness check trapped plugin-backed fields in the static
    // branch with `setOptions([])` and never invoked the provider.
    if (field.options_source === 'plugin' && optionsProvider) {
      const result = optionsProvider(field.key)
      if (result instanceof Promise) {
        result.then(setOptions).catch(() => setOptions([]))
      } else {
        setOptions(result)
      }
      return
    }
    if (field.options && field.options.length > 0) {
      setOptions(field.options)
      return
    }
    if (optionsProvider) {
      const result = optionsProvider(field.key)
      if (result instanceof Promise) {
        result.then(setOptions).catch(() => setOptions([]))
      } else {
        setOptions(result)
      }
    }
  }, [field, optionsProvider])

  return (
    <div>
      <label className={LABEL}>
        {field.label}
        {field.required ? ' *' : ''}
      </label>
      <select value={value} onChange={(e) => onChange(e.target.value)} className={SELECT}>
        <option value="" style={OPTION_STYLE}>
          —
        </option>
        {options.map((o) => (
          <option key={o.value ?? ''} value={o.value ?? ''} style={OPTION_STYLE}>
            {o.label}
          </option>
        ))}
      </select>
      {field.description && <p className={DESCRIPTION}>{field.description}</p>}
    </div>
  )
}
