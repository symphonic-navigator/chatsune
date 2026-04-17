from dataclasses import dataclass


@dataclass(frozen=True)
class TopicDefinition:
    name: str
    persist: bool = True

    def __str__(self) -> str:
        return self.name


class Topics:
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_DELETED = "user.deleted"
    USER_PASSWORD_RESET = "user.password_reset"
    USER_PROFILE_UPDATED = "user.profile.updated"
    AUDIT_LOGGED = "audit.logged"
    ERROR = "error"
    PERSONA_CREATED = "persona.created"
    PERSONA_UPDATED = "persona.updated"
    PERSONA_DELETED = "persona.deleted"
    PERSONA_REORDERED = "persona.reordered"
    LLM_USER_MODEL_CONFIG_UPDATED = "llm.user_model_config.updated"
    # --- LLM Connections (connections refactor) ---
    LLM_CONNECTION_CREATED = "llm.connection.created"
    LLM_CONNECTION_UPDATED = "llm.connection.updated"
    LLM_CONNECTION_REMOVED = "llm.connection.removed"
    LLM_CONNECTION_TESTED = "llm.connection.tested"
    LLM_CONNECTION_STATUS_CHANGED = "llm.connection.status_changed"
    LLM_CONNECTION_MODELS_REFRESHED = "llm.connection.models_refreshed"
    LLM_CONNECTION_SLUG_RENAMED = "llm.connection.slug_renamed"
    LLM_MODEL_PULL_STARTED = "llm.model.pull.started"
    LLM_MODEL_PULL_PROGRESS = "llm.model.pull.progress"
    LLM_MODEL_PULL_COMPLETED = "llm.model.pull.completed"
    LLM_MODEL_PULL_FAILED = "llm.model.pull.failed"
    LLM_MODEL_PULL_CANCELLED = "llm.model.pull.cancelled"
    LLM_MODEL_DELETED = "llm.model.deleted"
    # --- LLM Homelabs (community provisioning) ---
    LLM_HOMELAB_CREATED = "llm.homelab.created"
    LLM_HOMELAB_UPDATED = "llm.homelab.updated"
    LLM_HOMELAB_DELETED = "llm.homelab.deleted"
    LLM_HOMELAB_HOST_KEY_REGENERATED = "llm.homelab.host_key_regenerated"
    LLM_HOMELAB_STATUS_CHANGED = "llm.homelab.status_changed"
    LLM_HOMELAB_LAST_SEEN = "llm.homelab.last_seen"
    LLM_API_KEY_CREATED = "llm.api_key.created"
    LLM_API_KEY_UPDATED = "llm.api_key.updated"
    LLM_API_KEY_REVOKED = "llm.api_key.revoked"
    # --- Web Search ---
    WEBSEARCH_CREDENTIAL_SET = "websearch.credential.set"
    WEBSEARCH_CREDENTIAL_REMOVED = "websearch.credential.removed"
    WEBSEARCH_CREDENTIAL_TESTED = "websearch.credential.tested"
    SETTING_UPDATED = "setting.updated"
    SETTING_DELETED = "setting.deleted"
    SETTING_SYSTEM_PROMPT_UPDATED = "setting.system_prompt.updated"
    # Chat inference
    CHAT_STREAM_STARTED = "chat.stream.started"
    CHAT_CONTENT_DELTA = "chat.content.delta"
    CHAT_THINKING_DELTA = "chat.thinking.delta"
    CHAT_STREAM_ENDED = "chat.stream.ended"
    CHAT_STREAM_ERROR = "chat.stream.error"
    CHAT_STREAM_SLOW = "chat.stream.slow"
    CHAT_VISION_DESCRIPTION = "chat.vision.description"
    # Chat edit/regenerate
    CHAT_MESSAGE_CREATED = "chat.message.created"
    CHAT_MESSAGES_TRUNCATED = "chat.messages.truncated"
    CHAT_MESSAGE_UPDATED = "chat.message.updated"
    CHAT_MESSAGE_DELETED = "chat.message.deleted"
    CHAT_SESSION_TITLE_UPDATED = "chat.session.title_updated"
    CHAT_SESSION_CREATED = "chat.session.created"
    CHAT_SESSION_DELETED = "chat.session.deleted"
    CHAT_SESSION_RESTORED = "chat.session.restored"
    # Tool calls
    CHAT_TOOL_CALL_STARTED = "chat.tool_call.started"
    CHAT_TOOL_CALL_COMPLETED = "chat.tool_call.completed"
    CHAT_CLIENT_TOOL_DISPATCH = "chat.client_tool.dispatch"
    CHAT_WEB_SEARCH_CONTEXT = "chat.web_search.context"
    # Tool group toggles
    CHAT_SESSION_TOOLS_UPDATED = "chat.session.tools_updated"
    CHAT_SESSION_PINNED_UPDATED = "chat.session.pinned_updated"
    # MCP gateways
    MCP_TOOLS_REGISTER = "mcp.tools.register"
    MCP_TOOLS_REGISTERED = "mcp.tools.registered"
    MCP_GATEWAY_ERROR = "mcp.gateway.error"
    # Integrations
    INTEGRATION_CONFIG_UPDATED = "integration.config.updated"
    INTEGRATION_TOOL_DISPATCH = "integration.tool.dispatch"
    INTEGRATION_TOOL_RESULT = "integration.tool.result"
    INTEGRATION_ACTION_EXECUTED = "integration.action.executed"
    INTEGRATION_EMERGENCY_STOP = "integration.emergency_stop"
    # Storage
    STORAGE_FILE_UPLOADED = "storage.file.uploaded"
    STORAGE_FILE_DELETED = "storage.file.deleted"
    STORAGE_FILE_RENAMED = "storage.file.renamed"
    STORAGE_QUOTA_WARNING = "storage.quota.warning"
    # Bookmarks
    BOOKMARK_CREATED = "bookmark.created"
    BOOKMARK_UPDATED = "bookmark.updated"
    BOOKMARK_DELETED = "bookmark.deleted"
    # Projects
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    # Background jobs
    JOB_STARTED = "job.started"
    JOB_COMPLETED = "job.completed"
    JOB_FAILED = "job.failed"
    JOB_RETRY = "job.retry"
    JOB_EXPIRED = "job.expired"
    # Memory
    MEMORY_EXTRACTION_STARTED = "memory.extraction.started"
    MEMORY_EXTRACTION_COMPLETED = "memory.extraction.completed"
    MEMORY_EXTRACTION_FAILED = "memory.extraction.failed"
    MEMORY_EXTRACTION_SKIPPED = "memory.extraction.skipped"
    MEMORY_ENTRY_CREATED = "memory.entry.created"
    MEMORY_ENTRY_COMMITTED = "memory.entry.committed"
    MEMORY_ENTRY_UPDATED = "memory.entry.updated"
    MEMORY_ENTRY_DELETED = "memory.entry.deleted"
    MEMORY_ENTRY_AUTO_COMMITTED = "memory.entry.auto_committed"
    MEMORY_ENTRY_AUTHORED_BY_PERSONA = "memory.entry.authored_by_persona"
    MEMORY_DREAM_STARTED = "memory.dream.started"
    MEMORY_DREAM_COMPLETED = "memory.dream.completed"
    MEMORY_DREAM_FAILED = "memory.dream.failed"
    MEMORY_ENTRIES_DISCARDED = "memory.entries.discarded"
    MEMORY_BODY_ROLLBACK = "memory.body.rollback"
    MEMORY_BODY_UPDATED = "memory.body.updated"
    MEMORY_BODY_VERSION_DELETED = "memory.body.version_deleted"
    # Embedding
    EMBEDDING_MODEL_LOADING = "embedding.model.loading"
    EMBEDDING_MODEL_READY = "embedding.model.ready"
    EMBEDDING_BATCH_COMPLETED = "embedding.batch.completed"
    EMBEDDING_ERROR = "embedding.error"
    # Knowledge
    KNOWLEDGE_LIBRARY_CREATED = "knowledge.library.created"
    KNOWLEDGE_LIBRARY_UPDATED = "knowledge.library.updated"
    KNOWLEDGE_LIBRARY_DELETED = "knowledge.library.deleted"
    KNOWLEDGE_DOCUMENT_CREATED = "knowledge.document.created"
    KNOWLEDGE_DOCUMENT_UPDATED = "knowledge.document.updated"
    KNOWLEDGE_DOCUMENT_DELETED = "knowledge.document.deleted"
    KNOWLEDGE_DOCUMENT_EMBEDDING = "knowledge.document.embedding"
    KNOWLEDGE_DOCUMENT_EMBEDDED = "knowledge.document.embedded"
    KNOWLEDGE_DOCUMENT_EMBED_FAILED = "knowledge.document.embed_failed"
    KNOWLEDGE_SEARCH_COMPLETED = "knowledge.search.completed"
    # Artefacts
    ARTEFACT_CREATED = "artefact.created"
    ARTEFACT_UPDATED = "artefact.updated"
    ARTEFACT_DELETED = "artefact.deleted"
    ARTEFACT_UNDO = "artefact.undo"
    ARTEFACT_REDO = "artefact.redo"
    # Admin debug — broadcast to admin role only
    DEBUG_INFERENCE_STARTED = "debug.inference.started"
    DEBUG_INFERENCE_FINISHED = "debug.inference.finished"
    DEBUG_SNAPSHOT = "debug.snapshot"
    # Integrations — secrets hydration (ephemeral, not persisted)
    INTEGRATION_SECRETS_HYDRATED = TopicDefinition(
        "integration.secrets.hydrated", persist=False,
    )
    INTEGRATION_SECRETS_CLEARED = TopicDefinition(
        "integration.secrets.cleared", persist=False,
    )
