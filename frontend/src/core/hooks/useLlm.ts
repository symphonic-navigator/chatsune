// TODO Phase 9: rewrite this convenience hook against the new
// adapters/connections/models pipeline. All exported helpers are
// placeholders that throw on use — consumers are stubbed anyway.

const NOT_IMPLEMENTED = "useLlm: removed during connections refactor (Phase 9 rewrite pending)"

export function useLlm() {
  return {
    providers: [],
    models: new Map(),
    userConfigs: [],
    isLoading: false,
    error: null as string | null,
    fetchProviders: () => {
      throw new Error(NOT_IMPLEMENTED)
    },
    fetchModels: (_connectionId: string) => {
      throw new Error(NOT_IMPLEMENTED)
    },
    fetchUserConfigs: () => {
      throw new Error(NOT_IMPLEMENTED)
    },
  }
}
