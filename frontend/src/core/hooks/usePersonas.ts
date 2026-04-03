import { useCallback, useEffect, useState } from "react"
import { personasApi } from "../api/personas"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { PersonaDto, CreatePersonaRequest, UpdatePersonaRequest } from "../types/persona"

export function usePersonas() {
  const [personas, setPersonas] = useState<PersonaDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await personasApi.list()
      setPersonas(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load personas")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.PERSONA_CREATED, () => fetch()),
      eventBus.on(Topics.PERSONA_UPDATED, () => fetch()),
      eventBus.on(Topics.PERSONA_DELETED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const create = useCallback(async (data: CreatePersonaRequest) => {
    return personasApi.create(data)
  }, [])

  const update = useCallback(async (personaId: string, data: UpdatePersonaRequest) => {
    return personasApi.update(personaId, data)
  }, [])

  const remove = useCallback(async (personaId: string) => {
    return personasApi.remove(personaId)
  }, [])

  return { personas, isLoading, error, fetch, create, update, remove }
}
