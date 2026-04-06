import { useEffect, useState } from 'react'
import { personasApi } from '../api/personas'

/**
 * Fetches a short-lived signed avatar URL for use in <img src>.
 * Returns null while loading or if the persona has no avatar.
 */
export function useAvatarSrc(
  personaId: string,
  hasImage: boolean,
  updatedAt?: string,
): string | null {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    if (!hasImage) {
      setSrc(null)
      return
    }
    let mounted = true
    personasApi.avatarSrc(personaId, updatedAt).then((url) => {
      if (mounted) setSrc(url)
    }).catch(() => {
      if (mounted) setSrc(null)
    })
    return () => { mounted = false }
  }, [personaId, hasImage, updatedAt])

  return src
}
