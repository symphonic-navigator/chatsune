import { useCallback, useEffect, useState } from "react"
import { personasApi } from "../api/personas"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { BaseEvent } from "../types/events"
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
      eventBus.on(Topics.PERSONA_CREATED, (event: BaseEvent) => {
        const persona = event.payload.persona as unknown as PersonaDto
        if (!persona) return
        setPersonas((prev) =>
          prev.some((p) => p.id === persona.id) ? prev : [...prev, persona],
        )
      }),
      eventBus.on(Topics.PERSONA_UPDATED, (event: BaseEvent) => {
        const persona = event.payload.persona as unknown as PersonaDto
        if (!persona) return
        setPersonas((prev) =>
          prev.map((p) => (p.id === persona.id ? persona : p)),
        )
      }),
      eventBus.on(Topics.PERSONA_DELETED, (event: BaseEvent) => {
        const personaId = event.payload.persona_id as string
        if (!personaId) return
        setPersonas((prev) => prev.filter((p) => p.id !== personaId))
      }),
      eventBus.on(Topics.PERSONA_REORDERED, (event: BaseEvent) => {
        const orderedIds = event.payload.ordered_ids as string[] | undefined
        if (!orderedIds) return
        setPersonas((prev) => {
          const map = new Map(prev.map((p) => [p.id, p]))
          const reordered = orderedIds.map((id) => map.get(id)).filter(Boolean) as PersonaDto[]
          // Preserve any personas not present in ordered_ids (shouldn't normally happen)
          const seen = new Set(orderedIds)
          const leftover = prev.filter((p) => !seen.has(p.id))
          return [...reordered, ...leftover]
        })
      }),
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

  const reorder = async (orderedIds: string[]) => {
    setPersonas((prev) => {
      const map = new Map(prev.map((p) => [p.id, p]))
      return orderedIds.map((id) => map.get(id)!).filter(Boolean)
    })
    try {
      await personasApi.reorder(orderedIds)
    } catch {
      await fetch()
    }
  }

  return { personas, isLoading, error, fetch, create, update, remove, reorder }
}
