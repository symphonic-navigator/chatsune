import type { SVGProps } from 'react'

/**
 * Closed-padlock glyph — replacement for the 🔒 emoji.
 * Renders at the surrounding font-size and inherits the current text colour.
 * Source: svgrepo.com (lock-close-solid-svgrepo-com.svg).
 */
export function LockClosedIcon(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      xmlns="http://www.w3.org/2000/svg"
      viewBox="0 0 48 48"
      width="1em"
      height="1em"
      fill="currentColor"
      aria-hidden="true"
      {...props}
    >
      <path d="M40 18h-4v-5A11 11 0 0 0 25 2h-2a11 11 0 0 0-11 11v5H8a2 2 0 0 0-2 2v24a2 2 0 0 0 2 2h32a2 2 0 0 0 2-2V20a2 2 0 0 0-2-2zM25.9 33.4v2.5a2 2 0 0 1-4 0v-2.5a4 4 0 1 1 4 0zM32 18H16v-5a7 7 0 0 1 7-7h2a7 7 0 0 1 7 7z" />
    </svg>
  )
}
