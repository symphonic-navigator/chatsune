import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useIsPwa } from '../useIsPwa'
import { usePwaInstallStore } from '../../pwa/installPrompt'

describe('useIsPwa', () => {
  beforeEach(() => {
    usePwaInstallStore.setState({ isInstalled: false })
  })

  it('returns false when not installed', () => {
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(false)
  })

  it('returns true when installed flag is set', () => {
    usePwaInstallStore.setState({ isInstalled: true })
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(true)
  })

  it('updates when the store flag flips', () => {
    const { result } = renderHook(() => useIsPwa())
    expect(result.current).toBe(false)
    act(() => {
      usePwaInstallStore.setState({ isInstalled: true })
    })
    expect(result.current).toBe(true)
  })
})
