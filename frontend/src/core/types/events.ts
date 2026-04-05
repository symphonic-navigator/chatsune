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
  LLM_MODELS_FETCH_STARTED: "llm.models.fetch_started",
  LLM_MODELS_FETCH_COMPLETED: "llm.models.fetch_completed",
  LLM_USER_MODEL_CONFIG_UPDATED: "llm.user_model_config.updated",
  SETTING_UPDATED: "setting.updated",
  SETTING_DELETED: "setting.deleted",
  SETTING_SYSTEM_PROMPT_UPDATED: "setting.system_prompt.updated",
  CHAT_STREAM_STARTED: "chat.stream.started",
  CHAT_CONTENT_DELTA: "chat.content.delta",
  CHAT_THINKING_DELTA: "chat.thinking.delta",
  CHAT_STREAM_ENDED: "chat.stream.ended",
  CHAT_STREAM_ERROR: "chat.stream.error",
  CHAT_MESSAGES_TRUNCATED: "chat.messages.truncated",
  CHAT_MESSAGE_UPDATED: "chat.message.updated",
  CHAT_MESSAGE_DELETED: "chat.message.deleted",
  CHAT_SESSION_TITLE_UPDATED: "chat.session.title_updated",
  CHAT_SESSION_CREATED: "chat.session.created",
  CHAT_SESSION_DELETED: "chat.session.deleted",
  CHAT_TOOL_CALL_STARTED: "chat.tool_call.started",
  CHAT_TOOL_CALL_COMPLETED: "chat.tool_call.completed",
  CHAT_WEB_SEARCH_CONTEXT: "chat.web_search.context",
  CHAT_SESSION_TOOLS_UPDATED: "chat.session.tools_updated",
  CHAT_SESSION_PINNED_UPDATED: "chat.session.pinned_updated",
  BOOKMARK_CREATED: "bookmark.created",
  BOOKMARK_UPDATED: "bookmark.updated",
  BOOKMARK_DELETED: "bookmark.deleted",
} as const

export type TopicType = (typeof Topics)[keyof typeof Topics]
