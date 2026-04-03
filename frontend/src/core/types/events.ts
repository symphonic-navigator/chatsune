export interface BaseEvent {
  id: string
  type: string
  sequence: string
  scope: string
  correlation_id: string
  timestamp: string
  payload: Record<string, unknown>
}

export interface ErrorEventPayload {
  correlation_id: string
  error_code: string
  recoverable: boolean
  user_message: string
  detail: string | null
}

export const Topics = {
  USER_CREATED: "user.created",
  USER_UPDATED: "user.updated",
  USER_DEACTIVATED: "user.deactivated",
  USER_PASSWORD_RESET: "user.password_reset",
  USER_PROFILE_UPDATED: "user.profile.updated",
  AUDIT_LOGGED: "audit.logged",
  ERROR: "error",
  PERSONA_CREATED: "persona.created",
  PERSONA_UPDATED: "persona.updated",
  PERSONA_DELETED: "persona.deleted",
  LLM_CREDENTIAL_SET: "llm.credential.set",
  LLM_CREDENTIAL_REMOVED: "llm.credential.removed",
  LLM_CREDENTIAL_TESTED: "llm.credential.tested",
  LLM_MODEL_CURATED: "llm.model.curated",
  LLM_MODELS_REFRESHED: "llm.models.refreshed",
  LLM_USER_MODEL_CONFIG_UPDATED: "llm.user_model_config.updated",
  SETTING_UPDATED: "setting.updated",
  SETTING_DELETED: "setting.deleted",
  SETTING_SYSTEM_PROMPT_UPDATED: "setting.system_prompt.updated",
} as const

export type TopicType = (typeof Topics)[keyof typeof Topics]
