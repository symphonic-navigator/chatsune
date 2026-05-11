"""Internal parser intermediate types for chatgpt_import."""

from datetime import datetime

from pydantic import BaseModel


class ParsedMessage(BaseModel):
    """A single message that survived parser filters."""
    role: str  # "user" or "assistant"
    content: str
    created_at: datetime
    imported_model_slug: str | None = None


class ParsedConversation(BaseModel):
    """A conversation reduced to its imported form."""
    chatgpt_conversation_id: str
    title: str
    create_time: datetime
    update_time: datetime
    default_model_slug: str | None
    messages: list[ParsedMessage]
    first_user_message_preview: str
    first_assistant_message_preview: str

    @property
    def message_count(self) -> int:
        return len(self.messages)
