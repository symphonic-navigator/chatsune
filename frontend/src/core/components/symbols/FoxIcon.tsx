import { useId, type SVGProps } from 'react'

/**
 * Branded Chatsune fox — replacement for the 🦊 emoji.
 * Mirrors the artwork used as PWA icon and favicon (`public/favicon.svg`).
 * Renders at the surrounding font-size; gradient IDs are scoped per-instance
 * so multiple foxes on the same page do not clash.
 */
export function FoxIcon(props: SVGProps<SVGSVGElement>) {
  const uid = useId()
  const headGrad = `${uid}-head`
  const earGlow = `${uid}-ear`
  const eyeGrad = `${uid}-eye`
  const cheekGlow = `${uid}-cheek`
  const outerGlow = `${uid}-outer`

  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="-5 -5 110 110"
      width="1em"
      height="1em"
      aria-hidden="true"
      {...props}
    >
      <defs>
        <radialGradient id={headGrad} cx="50%" cy="38%" r="65%">
          <stop offset="0%" stopColor="#5a3a82" />
          <stop offset="55%" stopColor="#2e1c48" />
          <stop offset="100%" stopColor="#120a1f" />
        </radialGradient>
        <radialGradient id={earGlow} cx="50%" cy="72%" r="70%">
          <stop offset="0%" stopColor="#e9d5ff" />
          <stop offset="45%" stopColor="#c084fc" />
          <stop offset="100%" stopColor="#5b1e7a" />
        </radialGradient>
        <radialGradient id={eyeGrad} cx="50%" cy="40%" r="60%">
          <stop offset="0%" stopColor="#fff4d4" />
          <stop offset="50%" stopColor="#ffc86b" />
          <stop offset="100%" stopColor="#c48938" />
        </radialGradient>
        <radialGradient id={cheekGlow} cx="50%" cy="50%" r="50%">
          <stop offset="0%" stopColor="#aa3bff" stopOpacity="0.28" />
          <stop offset="100%" stopColor="#aa3bff" stopOpacity="0" />
        </radialGradient>
        <filter id={outerGlow} x="-25%" y="-25%" width="150%" height="150%">
          <feGaussianBlur in="SourceAlpha" stdDeviation="1.2" result="blur" />
          <feFlood floodColor="#aa3bff" floodOpacity="0.55" />
          <feComposite in2="blur" operator="in" result="glow" />
          <feMerge>
            <feMergeNode in="glow" />
            <feMergeNode in="SourceGraphic" />
          </feMerge>
        </filter>
      </defs>
      <g filter={`url(#${outerGlow})`}>
        <path d="M14 44 L28 6 L44 42 Z" fill={`url(#${headGrad})`} />
        <path d="M22 40 L28 14 L38 38 Z" fill={`url(#${earGlow})`} />
        <path d="M86 44 L76 22 L58 40 Z" fill={`url(#${headGrad})`} />
        <path d="M76 22 Q73 30 68 36 L62 32 Q70 28 76 22 Z" fill={`url(#${earGlow})`} />
        <path d="M76 22 L76 28 L71 32 Z" fill="#120a1f" opacity="0.6" />
        <path
          d="M14 44 Q16 38 30 38 L50 32 L70 38 Q84 38 86 44 L66 74 Q50 90 34 74 Z"
          fill={`url(#${headGrad})`}
        />
        <ellipse cx="26" cy="58" rx="16" ry="10" fill={`url(#${cheekGlow})`} />
        <ellipse cx="74" cy="58" rx="16" ry="10" fill={`url(#${cheekGlow})`} />
        <path d="M50 54 L39 74 Q50 84 61 74 Z" fill="#3a2a50" opacity="0.5" />
        <ellipse cx="36" cy="56" rx="5.3" ry="6.8" fill={`url(#${eyeGrad})`} />
        <ellipse cx="64" cy="56" rx="5.3" ry="6.8" fill={`url(#${eyeGrad})`} />
        <ellipse cx="36" cy="56" rx="1.4" ry="5" fill="#120a1f" />
        <ellipse cx="64" cy="56" rx="1.4" ry="5" fill="#120a1f" />
        <circle cx="37.4" cy="53.2" r="1.1" fill="#fff" />
        <circle cx="65.4" cy="53.2" r="1.1" fill="#fff" />
        <ellipse cx="50" cy="78" rx="3.6" ry="2.8" fill="#120a1f" />
        <circle cx="49" cy="77" r="0.6" fill="#fff" opacity="0.55" />
      </g>
    </svg>
  )
}
