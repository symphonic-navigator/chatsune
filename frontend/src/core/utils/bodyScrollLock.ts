/**
 * Body-scroll-lock helper with reference counting.
 *
 * Multiple overlays (the mobile sidebar drawer, any open Sheet) may want to
 * freeze background scrolling at the same time. A naive implementation that
 * sets `document.body.style.overflow = 'hidden'` and restores the previous
 * value in its cleanup will clobber the other lock: the second consumer
 * captures `overflow: hidden` as "previous" and on its cleanup leaves the
 * body frozen forever.
 *
 * This helper keeps a module-scope counter. The first lock captures the
 * original overflow value and applies `hidden`; subsequent locks just
 * increment the counter. Unlocking decrements; only when the counter hits
 * zero is the original overflow restored.
 */

let lockCount = 0
let previousOverflow: string | null = null

export function lockBodyScroll(): void {
  if (typeof document === 'undefined') return
  if (lockCount === 0) {
    previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
  }
  lockCount += 1
}

export function unlockBodyScroll(): void {
  if (typeof document === 'undefined') return
  if (lockCount === 0) return
  lockCount -= 1
  if (lockCount === 0) {
    document.body.style.overflow = previousOverflow ?? ''
    previousOverflow = null
  }
}
