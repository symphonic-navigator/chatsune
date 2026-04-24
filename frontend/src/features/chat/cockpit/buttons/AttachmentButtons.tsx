import { CockpitButton } from '../CockpitButton'

type Props = {
  onClick: () => void
  disabled?: boolean
  disabledReason?: string
}

export function AttachButton({ onClick, disabled, disabledReason }: Props) {
  return (
    <CockpitButton
      icon="📎"
      state={disabled ? 'disabled' : 'idle'}
      label={disabled ? (disabledReason ?? 'Attachments unavailable') : 'Attach'}
      onClick={disabled ? undefined : onClick}
      panel={disabled && disabledReason ? <p className="text-white/70">{disabledReason}</p> : undefined}
    />
  )
}

export function CameraButton({ onClick, disabled, disabledReason }: Props) {
  return (
    <CockpitButton
      icon="📷"
      state={disabled ? 'disabled' : 'idle'}
      label={disabled ? (disabledReason ?? 'Camera unavailable') : 'Camera'}
      onClick={disabled ? undefined : onClick}
      panel={disabled && disabledReason ? <p className="text-white/70">{disabledReason}</p> : undefined}
    />
  )
}

export function BrowseButton({ onClick }: { onClick: () => void }) {
  return (
    <CockpitButton
      icon="🗂"
      state="idle"
      label="Browse uploads"
      onClick={onClick}
    />
  )
}
