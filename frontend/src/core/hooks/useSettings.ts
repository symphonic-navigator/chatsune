import { useCallback, useEffect, useState } from "react"
import { settingsApi } from "../api/settings"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { BaseEvent } from "../types/events"
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
      eventBus.on(Topics.SETTING_UPDATED, (event: BaseEvent) => {
        const key = event.payload.key as string
        const value = event.payload.value as string
        const updatedBy = event.payload.updated_by as string
        if (!key) return
        const dto: AppSettingDto = {
          key,
          value,
          updated_at: event.timestamp,
          updated_by: updatedBy,
        }
        setSettings((prev) => {
          const idx = prev.findIndex((s) => s.key === key)
          if (idx === -1) return [...prev, dto]
          return prev.map((s) => (s.key === key ? dto : s))
        })
      }),
      eventBus.on(Topics.SETTING_DELETED, (event: BaseEvent) => {
        const key = event.payload.key as string
        if (!key) return
        setSettings((prev) => prev.filter((s) => s.key !== key))
      }),
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
