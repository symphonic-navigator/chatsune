from pydantic import BaseModel


class ErrorEvent(BaseModel):
    type: str = "error"
    correlation_id: str
    error_code: str
    recoverable: bool
    user_message: str
    detail: str | None = None
