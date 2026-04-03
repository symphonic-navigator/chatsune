import { useCallback, useEffect, useState } from "react"
import { usersApi } from "../api/users"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type { UserDto, CreateUserRequest, UpdateUserRequest } from "../types/auth"

export function useUsers() {
  const [users, setUsers] = useState<UserDto[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetch = useCallback(async (skip = 0, limit = 50) => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await usersApi.list(skip, limit)
      setUsers(res.users)
      setTotal(res.total)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load users")
    } finally {
      setIsLoading(false)
    }
  }, [])

  useEffect(() => {
    fetch()

    const unsubs = [
      eventBus.on(Topics.USER_CREATED, () => fetch()),
      eventBus.on(Topics.USER_UPDATED, () => fetch()),
      eventBus.on(Topics.USER_DEACTIVATED, () => fetch()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetch])

  const create = useCallback(async (data: CreateUserRequest) => {
    return usersApi.create(data)
  }, [])

  const update = useCallback(async (userId: string, data: UpdateUserRequest) => {
    return usersApi.update(userId, data)
  }, [])

  const deactivate = useCallback(async (userId: string) => {
    return usersApi.deactivate(userId)
  }, [])

  const resetPassword = useCallback(async (userId: string) => {
    return usersApi.resetPassword(userId)
  }, [])

  return { users, total, isLoading, error, fetch, create, update, deactivate, resetPassword }
}
