import { useDisplaySettings } from '../../../core/store/displaySettingsStore'
import {
  UI_SCALE_OPTIONS,
  FONT_FAMILY_VALUES,
  FONT_SIZE_VALUES,
  LINE_HEIGHT_VALUES,
} from '../../../core/types/displaySettings'
import type { DisplaySettings } from '../../../core/types/displaySettings'

const LABEL = "block text-[10px] uppercase tracking-[0.15em] text-white/50 mb-2 font-mono"

interface ButtonGroupProps<T extends string | number> {
  options: { value: T; label: string }[]
  selected: T
  onChange: (value: T) => void
}

function ButtonGroup<T extends string | number>({ options, selected, onChange }: ButtonGroupProps<T>) {
  return (
    <div className="flex gap-1.5 flex-wrap">
      {options.map(({ value, label }) => {
        const active = value === selected
        return (
          <button
            key={String(value)}
            type="button"
            onClick={() => onChange(value)}
            className={[
              'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
              active
                ? 'border-gold/60 bg-gold/12 text-gold'
                : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
            ].join(' ')}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

export function SettingsTab() {
  const { settings, update } = useDisplaySettings()

  return (
    <div className="flex flex-col gap-6 p-6 max-w-xl">
      <div>
        <label className={LABEL}>Chat Font</label>
        <ButtonGroup<DisplaySettings['chatFontFamily']>
          options={[
            { value: 'serif', label: 'Serif (Lora)' },
            { value: 'sans-serif', label: 'Sans-serif' },
          ]}
          selected={settings.chatFontFamily}
          onChange={(v) => update({ chatFontFamily: v })}
        />
      </div>

      <div>
        <label className={LABEL}>Font Size</label>
        <ButtonGroup<DisplaySettings['chatFontSize']>
          options={[
            { value: 'normal', label: 'Normal' },
            { value: 'large', label: 'Large' },
            { value: 'very-large', label: 'Very Large' },
          ]}
          selected={settings.chatFontSize}
          onChange={(v) => update({ chatFontSize: v })}
        />
      </div>

      <div>
        <label className={LABEL}>Line Spacing</label>
        <ButtonGroup<DisplaySettings['chatLineHeight']>
          options={[
            { value: 'small', label: 'Small' },
            { value: 'normal', label: 'Normal' },
            { value: 'large', label: 'Large' },
            { value: 'very-large', label: 'XL' },
          ]}
          selected={settings.chatLineHeight}
          onChange={(v) => update({ chatLineHeight: v })}
        />
      </div>

      {/* Live preview of font settings */}
      <div
        className="rounded-lg border border-white/8 bg-white/[0.03] px-4 py-3"
        style={{
          fontFamily: FONT_FAMILY_VALUES[settings.chatFontFamily],
          fontSize: FONT_SIZE_VALUES[settings.chatFontSize],
          lineHeight: LINE_HEIGHT_VALUES[settings.chatLineHeight],
        }}
      >
        <p className={settings.whiteScript ? 'text-white/90' : 'text-white/60'}>
          The quick brown fox jumps over the lazy dog. This is how your chat
          messages will look.
        </p>
      </div>

      <div>
        <label className={LABEL}>UI Scale</label>
        <ButtonGroup<DisplaySettings['uiScale']>
          options={UI_SCALE_OPTIONS.map((v) => ({ value: v, label: `${v}%` }))}
          selected={settings.uiScale}
          onChange={(v) => update({ uiScale: v })}
        />
      </div>

      <div>
        <label className={LABEL}>White Script</label>
        <p className="text-[11px] text-white/40 font-mono mb-2 leading-relaxed">
          High-contrast mode for chat text.
        </p>
        <button
          type="button"
          onClick={() => update({ whiteScript: !settings.whiteScript })}
          className={[
            'px-3.5 py-1.5 rounded-lg text-[11px] font-mono transition-all border',
            settings.whiteScript
              ? 'border-gold/60 bg-gold/12 text-gold'
              : 'border-white/8 bg-transparent text-white/40 hover:text-white/65 hover:border-white/20',
          ].join(' ')}
        >
          {settings.whiteScript ? 'On' : 'Off'}
        </button>
      </div>
    </div>
  )
}
