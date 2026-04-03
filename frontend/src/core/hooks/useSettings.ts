import { useCallback, useEffect, useState } from "react"
import { settingsApi } from "../api/settings"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { AppSettingDto, SetSettingRequest } from "../types/settings"

export function useSettings() {
  const [settings, setSettings] = useState<AppSettingDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await settingsApi.list()
      setSettings(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load settings")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.SETTING_UPDATED, () => fetch()),
      eventBus.on(Topics.SETTING_DELETED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const set = useCallback(async (key: string, data: SetSettingRequest) => {
    return settingsApi.set(key, data)
  }, [])

  const remove = useCallback(async (key: string) => {
    return settingsApi.remove(key)
  }, [])

  return { settings, isLoading, error, fetch, set, remove }
}
