"""Public service surface for the chatgpt_import module."""
from __future__ import annotations

import hashlib
import logging
import secrets
import tempfile
from collections.abc import AsyncIterator
from pathlib import Path

from motor.motor_asyncio import AsyncIOMotorDatabase

from backend.jobs._models import JobType
from backend.modules.chatgpt_import._repository import ChatGptImportRepository
from shared.dtos.chatgpt_import import (
    ConversationItemDto,
    ImportDto,
    ImportedInfoDto,
)

_log = logging.getLogger(__name__)

# Placeholder ``model_unique_id`` used as the job's routing label for
# import-parse / import-conversation jobs. These jobs don't perform any
# LLM inference, but ``submit`` requires the field — the safeguard layer
# uses it to attribute spend; a non-LLM job records zero spend.
_IMPORT_JOB_MODEL_TAG = "chatgpt_import:internal"


class ImportConflictError(Exception):
    """Raised when an upload would replace an existing active import.

    Caller may retry the upload with ``replace_existing=True``.
    """
    def __init__(self, *, existing_import_id: str, message: str) -> None:
        super().__init__(message)
        self.existing_import_id = existing_import_id


class ImportNotFoundError(Exception):
    """Raised when an operation targets an import that does not exist."""


class ChatGptImportService:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._repo = ChatGptImportRepository(db)

    async def upload_streaming(
        self,
        *,
        user_id: str,
        stream: AsyncIterator[bytes],
        filename: str,
        replace_existing: bool = False,
    ) -> tuple[str, bool]:
        """Stream the request body to a temp file, dedupe by hash, dispatch parse.

        Returns ``(import_id, duplicate)``. ``duplicate`` is True iff the
        same ``sha256`` already existed for this user — in that case the
        original import_id is returned and no parsing is queued.
        """
        sha = hashlib.sha256()
        size = 0
        # delete=False so we control the lifetime; the parse-job handler
        # unlinks the file when it finishes.
        tmp = tempfile.NamedTemporaryFile(
            prefix="chatgpt_import_", suffix=".json", delete=False,
        )
        path = Path(tmp.name)
        try:
            async for chunk in stream:
                if not chunk:
                    continue
                sha.update(chunk)
                size += len(chunk)
                tmp.write(chunk)
        finally:
            tmp.close()

        file_hash = sha.hexdigest()

        # Dedupe by hash: same file already uploaded?
        existing = await self._repo.find_import_by_hash(user_id, file_hash)
        if existing:
            path.unlink(missing_ok=True)
            return str(existing["_id"]), True

        # One active upload per user.
        active = await self._repo.get_active_import(user_id)
        if active and not replace_existing:
            path.unlink(missing_ok=True)
            raise ImportConflictError(
                existing_import_id=str(active["_id"]),
                message="An active upload already exists",
            )
        if active and replace_existing:
            await self._repo.delete_import(str(active["_id"]))

        import_id = await self._repo.create_import(
            user_id=user_id,
            file_hash=file_hash,
            file_size_bytes=size,
            filename=filename,
        )

        # Deferred to break circular import: backend.jobs imports the
        # registry which (transitively) imports this module.
        from backend.jobs import submit

        correlation_id = f"import-parse-{secrets.token_hex(8)}"
        await submit(
            JobType.CHATGPT_IMPORT_PARSE,
            user_id=user_id,
            model_unique_id=_IMPORT_JOB_MODEL_TAG,
            payload={
                "user_id": user_id,
                "import_id": import_id,
                "file_path": str(path),
                "filename": filename,
                "file_size_bytes": size,
                "correlation_id": correlation_id,
            },
            correlation_id=correlation_id,
        )
        _log.info(
            "chatgpt_import.upload.dispatched",
            extra={
                "user_id": user_id,
                "import_id": import_id,
                "size_bytes": size,
                "correlation_id": correlation_id,
            },
        )
        return import_id, False

    async def trigger_conversation_imports(
        self,
        *,
        user_id: str,
        import_id: str,
        persona_id: str,
        chatgpt_conversation_ids: list[str],
    ) -> tuple[str, list[tuple[str, str]]]:
        """Queue one per-conversation import job for each id.

        Returns ``(correlation_id, [(conv_id, job_id), ...])``. The shared
        correlation id groups the per-conversation events from a single
        multi-select "Import" click so the frontend can show progress.
        """
        from backend.jobs import submit

        correlation_id = f"import-batch-{secrets.token_hex(6)}"
        jobs: list[tuple[str, str]] = []
        for cid in chatgpt_conversation_ids:
            job_id = await submit(
                JobType.CHATGPT_IMPORT_CONVERSATION,
                user_id=user_id,
                model_unique_id=_IMPORT_JOB_MODEL_TAG,
                payload={
                    "user_id": user_id,
                    "import_id": import_id,
                    "chatgpt_conversation_id": cid,
                    "persona_id": persona_id,
                    "correlation_id": correlation_id,
                },
                correlation_id=correlation_id,
            )
            jobs.append((cid, job_id))
        return correlation_id, jobs

    async def get_active_import_dto(
        self, *, user_id: str
    ) -> ImportDto | None:
        doc = await self._repo.get_active_import(user_id)
        if not doc:
            return None
        return _import_doc_to_dto(doc)

    async def list_conversations_for_ui(
        self,
        *,
        user_id: str,
        import_id: str,
        persona_names: dict[str, str],
        title_search: str | None = None,
        sort: str = "create_time_desc",
    ) -> list[ConversationItemDto]:
        docs = await self._repo.list_conversations(
            user_id=user_id,
            import_id=import_id,
            title_search=title_search,
            sort=sort,
        )
        return [_conv_doc_to_dto(d, persona_names) for d in docs]

    async def delete_import(
        self, *, user_id: str, import_id: str
    ) -> None:
        doc = await self._repo.get_import(import_id)
        if not doc or doc.get("user_id") != user_id:
            raise ImportNotFoundError(import_id)
        await self._repo.delete_import(import_id)


def _import_doc_to_dto(doc: dict) -> ImportDto:
    return ImportDto(
        import_id=str(doc["_id"]),
        filename=doc.get("uploaded_filename", ""),
        file_size_bytes=doc.get("file_size_bytes", 0),
        status=doc.get("status", "parsing"),
        conversation_count=doc.get("conversation_count", 0),
        skipped_count=doc.get("skipped_count", 0),
        skipped_reasons=doc.get("skipped_reasons", {}),
        created_at=doc["created_at"],
        expires_at=doc["expires_at"],
        last_import_at=doc.get("last_import_at"),
        error_message=doc.get("error_message"),
    )


def _conv_doc_to_dto(
    doc: dict, persona_names: dict[str, str]
) -> ConversationItemDto:
    imports = [
        ImportedInfoDto(
            persona_id=i["persona_id"],
            persona_name=persona_names.get(i["persona_id"], "(deleted persona)"),
            session_id=i["session_id"],
            imported_at=i["imported_at"],
        )
        for i in doc.get("imports", [])
    ]
    return ConversationItemDto(
        chatgpt_conversation_id=doc["chatgpt_conversation_id"],
        title=doc.get("title") or "",
        create_time=doc["create_time"],
        update_time=doc["update_time"],
        message_count=doc.get("message_count", 0),
        first_user_message_preview=doc.get("first_user_message_preview", ""),
        first_assistant_message_preview=doc.get("first_assistant_message_preview", ""),
        default_model_slug=doc.get("default_model_slug"),
        imports=imports,
    )
