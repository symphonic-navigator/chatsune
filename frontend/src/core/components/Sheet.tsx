import { useEffect, useRef } from 'react'
import { createPortal } from 'react-dom'
import { lockBodyScroll, unlockBodyScroll } from '../utils/bodyScrollLock'

/**
 * Responsive overlay container.
 *
 * Mobile (< lg): renders full-screen — the content container covers the
 * whole viewport, has no rounded corners, and scrolls internally.
 *
 * Desktop (>= lg): renders as a centred modal dialog with a dark backdrop
 * and the configured max-width. Visually and behaviourally equivalent to
 * the hand-rolled fixed-inset-0 modals that existed in the codebase prior
 * to this component, so Desktop consumers see no regression when they
 * migrate.
 *
 * Features:
 *   - Portal into `document.body` so stacking context is isolated.
 *   - Backdrop click + `Esc` key close the sheet.
 *   - Body-scroll-lock via the shared ref-counted helper.
 *   - Lightweight open/close transition (opacity + transform).
 *   - Auto-focus on the dialog root for basic keyboard access.
 *
 * Deliberately NOT implemented in this pass:
 *   - Swipe-to-dismiss on mobile. The `disableSwipeToDismiss` prop stays
 *     in the API so a future pass can add it without a breaking change.
 *   - Focus trap. Consumers that need it keep running their own
 *     `useFocusTrap` hook around their content.
 */

type SheetSize = 'sm' | 'md' | 'lg' | 'xl' | 'full'

interface SheetProps {
  isOpen: boolean
  onClose: () => void
  children: React.ReactNode
  /** Max-width on desktop. Defaults to 'lg'. */
  size?: SheetSize
  /** Reserved — currently has no effect. Swipe-to-dismiss is not yet implemented. */
  disableSwipeToDismiss?: boolean
  /** Accessible label for the dialog. */
  ariaLabel?: string
  /** Optional className for the inner content container — consumers use this
   *  to set background colour, padding and layout. */
  className?: string
}

const SIZE_MAX_W: Record<SheetSize, string> = {
  sm: 'lg:max-w-sm',
  md: 'lg:max-w-md',
  lg: 'lg:max-w-lg',
  xl: 'lg:max-w-2xl',
  full: 'lg:max-w-6xl',
}

export function Sheet({
  isOpen,
  onClose,
  children,
  size = 'lg',
  ariaLabel,
  className = '',
}: SheetProps) {
  const contentRef = useRef<HTMLDivElement>(null)

  // Esc closes the sheet while it is open.
  useEffect(() => {
    if (!isOpen) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [isOpen, onClose])

  // Lock background scrolling for the lifetime of the open sheet.
  useEffect(() => {
    if (!isOpen) return
    lockBodyScroll()
    return () => unlockBodyScroll()
  }, [isOpen])

  // Auto-focus the dialog root when it opens so keyboard users land on it.
  useEffect(() => {
    if (isOpen) {
      // Defer one frame to ensure the node is mounted before focusing.
      requestAnimationFrame(() => contentRef.current?.focus())
    }
  }, [isOpen])

  if (!isOpen) return null

  const maxWidth = SIZE_MAX_W[size]

  // Note: Toasts are layered at a higher z-index than the sheet so they
  // remain visible above any open sheet — see ToastContainer.
  return createPortal(
    <>
      {/* Backdrop — full viewport, click anywhere to dismiss. */}
      <div
        className="fixed inset-0 z-50 bg-black/60"
        onClick={onClose}
        aria-hidden="true"
      />

      {/*
        Centring wrapper. On mobile it is a no-op (the content container
        is itself inset-0); on desktop it centres the content with flex.
        Pointer-events are passed through the padding so clicks on the
        backdrop behind actually land on the backdrop element.
      */}
      <div className="pointer-events-none fixed inset-0 z-[51] flex items-stretch justify-stretch lg:items-center lg:justify-center lg:p-4">
        <div
          ref={contentRef}
          role="dialog"
          aria-modal="true"
          aria-label={ariaLabel}
          tabIndex={-1}
          className={[
            'pointer-events-auto flex w-full flex-col overflow-hidden outline-none',
            // Mobile: cover the whole viewport, no rounding.
            'h-full rounded-none',
            // Desktop: bounded width, rounded corners, soft height cap.
            'lg:h-auto lg:max-h-[calc(100dvh-2rem)] lg:rounded-xl',
            maxWidth,
            className,
          ].join(' ')}
        >
          {children}
        </div>
      </div>
    </>,
    document.body,
  )
}
