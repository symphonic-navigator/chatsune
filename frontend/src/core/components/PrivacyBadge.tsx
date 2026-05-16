import type { CSSProperties } from 'react'

type PrivacyBadgeProps = {
  className?: string
  style?: CSSProperties
  title?: string
}

const DEFAULT_TITLE =
  'Privacy-preserving — runs in confidential compute or with guaranteed zero data retention'

export function PrivacyBadge({ className, style, title }: PrivacyBadgeProps) {
  return (
    <span
      title={title ?? DEFAULT_TITLE}
      style={style}
      className={
        'inline-flex items-center rounded-full ' +
        'bg-emerald-500/15 border border-emerald-400/30 ' +
        'px-2 py-0.5 text-[10px] font-semibold tracking-wider ' +
        'text-emerald-300 uppercase ' +
        (className ?? '')
      }
    >
      Privacy
    </span>
  )
}
