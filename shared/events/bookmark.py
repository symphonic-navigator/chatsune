from datetime import datetime

from pydantic import BaseModel

from shared.dtos.bookmark import BookmarkDto


class BookmarkCreatedEvent(BaseModel):
    type: str = "bookmark.created"
    bookmark: BookmarkDto
    correlation_id: str
    timestamp: datetime


class BookmarkUpdatedEvent(BaseModel):
    type: str = "bookmark.updated"
    bookmark: BookmarkDto
    correlation_id: str
    timestamp: datetime


class BookmarkDeletedEvent(BaseModel):
    type: str = "bookmark.deleted"
    bookmark_id: str
    correlation_id: str
    timestamp: datetime
