import { useEffect, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'

export interface FloatingMenuProps {
  /** Whether the menu is open. The menu is unmounted when false. */
  open: boolean
  /** Called when the menu should close (click-outside, Escape, resize, scroll). */
  onClose: () => void
  /** Ref to the trigger element. Used to anchor the menu and to keep
   *  click-outside detection from firing on the trigger itself. */
  anchorRef: React.RefObject<HTMLElement | null>
  /** Menu width in pixels. Default 192 (Tailwind w-48). */
  width?: number
  /** Optional ARIA role override. Default `menu`. */
  role?: string
  /** Menu items. */
  children: React.ReactNode
}

const VIEWPORT_MARGIN = 8

/**
 * Renders a floating menu portalled to `document.body` with
 * edge-aware positioning. Default placement is below the anchor,
 * with the menu's right edge aligned to the anchor's right edge.
 * Flips upward when below would overflow the viewport bottom and
 * leftward becomes rightward when the menu would overflow the
 * viewport's left edge. All flips keep an 8 px margin from the
 * viewport edges.
 *
 * Closes on click outside (anchor and menu both excluded), Escape,
 * window resize, and window scroll. The latter two avoid having to
 * recompute on every layout event — the user can re-open after.
 */
export function FloatingMenu({
  open,
  onClose,
  anchorRef,
  width = 192,
  role = 'menu',
  children,
}: FloatingMenuProps) {
  const menuRef = useRef<HTMLDivElement>(null)
  const [position, setPosition] = useState<{ top: number; left: number } | null>(null)

  useLayoutEffect(() => {
    if (!open) {
      setPosition(null)
      return
    }
    // useLayoutEffect runs after refs are attached and DOM is committed,
    // so menuRef.current.offsetHeight reflects the real mounted height.
    const anchor = anchorRef.current
    const menu = menuRef.current
    if (!anchor || !menu) return

    // The app's <body> has `transform: scale(var(--ui-scale))` (see
    // index.css). Body therefore becomes the containing block for any
    // `position: fixed` descendant, which means our menu's top/left
    // are interpreted in body's pre-transform coordinate space and
    // then re-scaled by the transform. getBoundingClientRect() and
    // window.innerWidth/innerHeight however report visual viewport
    // coordinates (post-transform). We compensate by dividing every
    // viewport-derived input by --ui-scale so the math is consistent
    // in body coords. menu.offsetHeight is already in body coords
    // (layout pixels, pre-transform), so it stays unscaled.
    const scale =
      parseFloat(
        getComputedStyle(document.documentElement).getPropertyValue('--ui-scale'),
      ) || 1

    const a = anchor.getBoundingClientRect()
    const menuHeight = menu.offsetHeight
    const vw = window.innerWidth / scale
    const vh = window.innerHeight / scale
    const margin = VIEWPORT_MARGIN / scale
    const gap = 4 / scale

    const aTop = a.top / scale
    const aBottom = a.bottom / scale
    const aLeft = a.left / scale
    const aRight = a.right / scale

    // Default: below the anchor, right edges aligned (body coords).
    let top = aBottom + gap
    let left = aRight - width

    // Vertical flip: open above when below would overflow.
    if (top + menuHeight > vh - margin) {
      top = aTop - menuHeight - gap
    }
    // Horizontal flip: align to anchor's left edge when default
    // would overflow the viewport's left edge.
    if (left < margin) {
      left = aLeft
    }
    // Defensive clamp so the menu always stays inside the viewport
    // with the configured margin (all in body coords).
    top = Math.max(margin, Math.min(top, vh - menuHeight - margin))
    left = Math.max(margin, Math.min(left, vw - width - margin))

    setPosition({ top, left })
  }, [open, anchorRef, width])

  useEffect(() => {
    if (!open) return
    const onMouseDown = (e: MouseEvent) => {
      const t = e.target as Node
      if (anchorRef.current?.contains(t)) return
      if (menuRef.current?.contains(t)) return
      onClose()
    }
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    const onResize = () => onClose()
    const onScroll = () => onClose()
    document.addEventListener('mousedown', onMouseDown)
    document.addEventListener('keydown', onKeyDown)
    window.addEventListener('resize', onResize)
    // capture so that scroll inside any scrollable ancestor closes the menu.
    window.addEventListener('scroll', onScroll, true)
    return () => {
      document.removeEventListener('mousedown', onMouseDown)
      document.removeEventListener('keydown', onKeyDown)
      window.removeEventListener('resize', onResize)
      window.removeEventListener('scroll', onScroll, true)
    }
  }, [open, anchorRef, onClose])

  if (!open) return null

  // Portal to <body>. The position computation above already
  // compensates for body's `transform: scale(var(--ui-scale))` so
  // top/left are expressed in body's pre-transform coord space; the
  // transform then re-scales them to the correct visual position.
  return createPortal(
    <div
      ref={menuRef}
      role={role}
      className="z-50 rounded-lg border border-white/10 bg-elevated py-1 shadow-xl"
      style={{
        position: 'fixed',
        top: position?.top ?? -9999,
        left: position?.left ?? -9999,
        width,
        visibility: position === null ? 'hidden' : 'visible',
      }}
      onClick={(e) => e.stopPropagation()}
    >
      {children}
    </div>,
    document.body,
  )
}
