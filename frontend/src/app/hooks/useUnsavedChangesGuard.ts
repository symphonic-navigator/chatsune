import { useCallback, useState } from "react"

interface UseUnsavedChangesGuardResult {
  /** True while the inline confirmation prompt should be shown. */
  confirmingClose: boolean
  /**
   * Call from the close handler. If the form is dirty this flips
   * `confirmingClose` to true and does NOT close. If the form is clean
   * it invokes `onConfirmClose` immediately.
   */
  attemptClose: () => void
  /** User confirmed they want to discard changes — actually close. */
  confirmDiscard: () => void
  /** User cancelled the discard prompt — keep editing. */
  cancelDiscard: () => void
}

/**
 * Guards a modal/editor against accidental close when there are unsaved
 * changes. The caller renders an inline confirmation UI based on
 * `confirmingClose`.
 */
export function useUnsavedChangesGuard(
  isDirty: boolean,
  onConfirmClose: () => void,
): UseUnsavedChangesGuardResult {
  const [confirmingClose, setConfirmingClose] = useState(false)

  const attemptClose = useCallback(() => {
    if (isDirty) {
      setConfirmingClose(true)
      return
    }
    onConfirmClose()
  }, [isDirty, onConfirmClose])

  const confirmDiscard = useCallback(() => {
    setConfirmingClose(false)
    onConfirmClose()
  }, [onConfirmClose])

  const cancelDiscard = useCallback(() => {
    setConfirmingClose(false)
  }, [])

  return { confirmingClose, attemptClose, confirmDiscard, cancelDiscard }
}
