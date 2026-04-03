import { useCallback, useEffect, useState } from "react"
import { llmApi } from "../api/llm"
import { eventBus } from "../websocket/eventBus"
import { Topics } from "../types/events"
import type {
  ProviderCredentialDto,
  ModelMetaDto,
  UserModelConfigDto,
  SetProviderKeyRequest,
  SetModelCurationRequest,
  SetUserModelConfigRequest,
} from "../types/llm"

export function useLlm() {
  const [providers, setProviders] = useState<ProviderCredentialDto[]>([])
  const [models, setModels] = useState<Map<string, ModelMetaDto[]>>(new Map())
  const [userConfigs, setUserConfigs] = useState<UserModelConfigDto[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const fetchProviders = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const res = await llmApi.listProviders()
      setProviders(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load providers")
    } finally {
      setIsLoading(false)
    }
  }, [])

  const fetchModels = useCallback(async (providerId: string) => {
    try {
      const res = await llmApi.listModels(providerId)
      setModels((prev) => new Map(prev).set(providerId, res))
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load models")
    }
  }, [])

  const fetchUserConfigs = useCallback(async () => {
    try {
      const res = await llmApi.listUserConfigs()
      setUserConfigs(res)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load user configs")
    }
  }, [])

  useEffect(() => {
    fetchProviders()
    fetchUserConfigs()

    const unsubs = [
      eventBus.on(Topics.LLM_CREDENTIAL_SET, () => fetchProviders()),
      eventBus.on(Topics.LLM_CREDENTIAL_REMOVED, () => fetchProviders()),
      eventBus.on(Topics.LLM_MODEL_CURATED, () => {
        // Refetch models for all loaded providers
        models.forEach((_, pid) => fetchModels(pid))
      }),
      eventBus.on(Topics.LLM_MODELS_REFRESHED, () => {
        models.forEach((_, pid) => fetchModels(pid))
      }),
      eventBus.on(Topics.LLM_USER_MODEL_CONFIG_UPDATED, () => fetchUserConfigs()),
    ]

    return () => unsubs.forEach((u) => u())
  }, [fetchProviders, fetchModels, fetchUserConfigs])

  const setKey = useCallback(async (providerId: string, data: SetProviderKeyRequest) => {
    return llmApi.setKey(providerId, data)
  }, [])

  const removeKey = useCallback(async (providerId: string) => {
    return llmApi.removeKey(providerId)
  }, [])

  const testKey = useCallback(async (providerId: string, data: SetProviderKeyRequest) => {
    return llmApi.testKey(providerId, data)
  }, [])

  const setCuration = useCallback(async (providerId: string, modelSlug: string, data: SetModelCurationRequest) => {
    return llmApi.setCuration(providerId, modelSlug, data)
  }, [])

  const removeCuration = useCallback(async (providerId: string, modelSlug: string) => {
    return llmApi.removeCuration(providerId, modelSlug)
  }, [])

  const setUserConfig = useCallback(async (providerId: string, modelSlug: string, data: SetUserModelConfigRequest) => {
    return llmApi.setUserConfig(providerId, modelSlug, data)
  }, [])

  const deleteUserConfig = useCallback(async (providerId: string, modelSlug: string) => {
    return llmApi.deleteUserConfig(providerId, modelSlug)
  }, [])

  return {
    providers,
    models,
    userConfigs,
    isLoading,
    error,
    fetchProviders,
    fetchModels,
    fetchUserConfigs,
    setKey,
    removeKey,
    testKey,
    setCuration,
    removeCuration,
    setUserConfig,
    deleteUserConfig,
  }
}
