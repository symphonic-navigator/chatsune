from datetime import UTC, datetime
from uuid import uuid4

import logging

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ReturnDocument
from pymongo.errors import OperationFailure

_log = logging.getLogger(__name__)

from shared.dtos.knowledge import (
    KnowledgeDocumentDetailDto,
    KnowledgeDocumentDto,
    KnowledgeLibraryDto,
)


class KnowledgeRepository:
    def __init__(self, db: AsyncIOMotorDatabase) -> None:
        self._libraries = db["knowledge_libraries"]
        self._documents = db["knowledge_documents"]
        self._chunks = db["knowledge_chunks"]

    async def create_indexes(self) -> None:
        await self._libraries.create_index("user_id")
        await self._libraries.create_index([("user_id", 1), ("nsfw", 1)])

        await self._documents.create_index("user_id")
        await self._documents.create_index([("user_id", 1), ("library_id", 1)])
        await self._documents.create_index([("user_id", 1), ("embedding_status", 1)])

        await self._chunks.create_index("user_id")
        await self._chunks.create_index([("user_id", 1), ("document_id", 1)])
        await self._chunks.create_index([("user_id", 1), ("library_id", 1)])

        # Vector Search index — requires mongodb-atlas-local image with mongot.
        # Ensure collection exists before creating search index.
        db = self._chunks.database
        existing = await db.list_collection_names()
        if "knowledge_chunks" not in existing:
            await db.create_collection("knowledge_chunks")

        try:
            await self._chunks.create_search_index(
                {
                    "definition": {
                        "fields": [
                            {
                                "type": "vector",
                                "path": "vector",
                                "numDimensions": 768,
                                "similarity": "cosine",
                            },
                            {"type": "filter", "path": "user_id"},
                            {"type": "filter", "path": "library_id"},
                        ],
                    },
                    "name": "knowledge_vector_index",
                    "type": "vectorSearch",
                }
            )
            _log.info("Created knowledge vector search index")
        except OperationFailure as exc:
            if "already exists" in str(exc):
                _log.debug("Knowledge vector search index already exists")
            else:
                raise

    # ------------------------------------------------------------------
    # Libraries
    # ------------------------------------------------------------------

    async def create_library(
        self,
        user_id: str,
        name: str,
        description: str | None,
        nsfw: bool,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "name": name,
            "description": description,
            "nsfw": nsfw,
            "document_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._libraries.insert_one(doc)
        return doc

    async def get_library(self, library_id: str, user_id: str) -> dict | None:
        return await self._libraries.find_one({"_id": library_id, "user_id": user_id})

    async def list_libraries(self, user_id: str) -> list[dict]:
        cursor = self._libraries.find({"user_id": user_id}).sort("name", 1)
        return await cursor.to_list(length=1000)

    async def update_library(
        self, library_id: str, user_id: str, updates: dict
    ) -> dict | None:
        updates["updated_at"] = datetime.now(UTC)
        return await self._libraries.find_one_and_update(
            {"_id": library_id, "user_id": user_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )

    async def delete_library(self, library_id: str, user_id: str) -> bool:
        """Cascade-delete a library and return whether the library doc was removed.

        Kept for backwards compatibility (notably the knowledge import rollback
        path). For full per-step counts use :meth:`delete_library_with_counts`.
        """
        result = await self.delete_library_with_counts(library_id, user_id)
        return result["library_deleted"]

    async def delete_library_with_counts(
        self, library_id: str, user_id: str,
    ) -> dict:
        """Cascade-delete a library, returning per-step counts.

        Returns ``{"library_deleted": bool, "documents_deleted": int,
        "chunks_deleted": int}``. Embedding vectors live inside the chunks
        collection and are removed implicitly with the chunk delete.
        """
        # Collect document IDs for cascade
        cursor = self._documents.find(
            {"library_id": library_id, "user_id": user_id},
            {"_id": 1},
        )
        doc_ids = [d["_id"] async for d in cursor]

        # Cascade: delete chunks for all documents in this library
        chunks_deleted = 0
        if doc_ids:
            chunk_result = await self._chunks.delete_many(
                {"document_id": {"$in": doc_ids}, "user_id": user_id},
            )
            chunks_deleted = chunk_result.deleted_count

        # Cascade: delete all documents in this library
        doc_result = await self._documents.delete_many(
            {"library_id": library_id, "user_id": user_id},
        )

        lib_result = await self._libraries.delete_one(
            {"_id": library_id, "user_id": user_id},
        )
        return {
            "library_deleted": lib_result.deleted_count > 0,
            "documents_deleted": doc_result.deleted_count,
            "chunks_deleted": chunks_deleted,
        }

    async def increment_document_count(
        self, library_id: str, user_id: str, delta: int
    ) -> None:
        await self._libraries.update_one(
            {"_id": library_id, "user_id": user_id},
            {
                "$inc": {"document_count": delta},
                "$set": {"updated_at": datetime.now(UTC)},
            },
        )

    # ------------------------------------------------------------------
    # Documents
    # ------------------------------------------------------------------

    async def create_document(
        self,
        user_id: str,
        library_id: str,
        title: str,
        content: str,
        media_type: str,
    ) -> dict:
        now = datetime.now(UTC)
        doc = {
            "_id": str(uuid4()),
            "user_id": user_id,
            "library_id": library_id,
            "title": title,
            "content": content,
            "media_type": media_type,
            "size_bytes": len(content.encode("utf-8")),
            "chunk_count": 0,
            "embedding_status": "pending",
            "embedding_error": None,
            "retry_count": 0,
            "created_at": now,
            "updated_at": now,
        }
        await self._documents.insert_one(doc)
        return doc

    async def get_document(self, doc_id: str, user_id: str) -> dict | None:
        return await self._documents.find_one({"_id": doc_id, "user_id": user_id})

    async def list_documents(self, library_id: str, user_id: str) -> list[dict]:
        # Exclude content field for list view
        cursor = self._documents.find(
            {"library_id": library_id, "user_id": user_id},
            {"content": 0},
        ).sort("title", 1)
        return await cursor.to_list(length=10000)

    async def update_document(
        self, doc_id: str, user_id: str, updates: dict
    ) -> dict | None:
        if "content" in updates:
            updates["size_bytes"] = len(updates["content"].encode("utf-8"))
        updates["updated_at"] = datetime.now(UTC)
        return await self._documents.find_one_and_update(
            {"_id": doc_id, "user_id": user_id},
            {"$set": updates},
            return_document=ReturnDocument.AFTER,
        )

    async def set_embedding_status(
        self,
        doc_id: str,
        user_id: str,
        status: str,
        chunk_count: int = 0,
        error: str | None = None,
    ) -> None:
        updates: dict = {
            "embedding_status": status,
            "embedding_error": error,
            "updated_at": datetime.now(UTC),
        }
        if chunk_count:
            updates["chunk_count"] = chunk_count
        await self._documents.update_one(
            {"_id": doc_id, "user_id": user_id},
            {"$set": updates},
        )

    async def increment_retry_count(self, doc_id: str, user_id: str) -> int:
        result = await self._documents.find_one_and_update(
            {"_id": doc_id, "user_id": user_id},
            {"$inc": {"retry_count": 1}},
            return_document=ReturnDocument.AFTER,
            projection={"retry_count": 1},
        )
        return result["retry_count"] if result else 0

    async def reset_retry_count(self, doc_id: str, user_id: str) -> None:
        await self._documents.update_one(
            {"_id": doc_id, "user_id": user_id},
            {"$set": {"retry_count": 0}},
        )

    async def delete_document(self, doc_id: str, user_id: str) -> str | None:
        doc = await self._documents.find_one(
            {"_id": doc_id, "user_id": user_id},
            {"library_id": 1},
        )
        if not doc:
            return None

        library_id = doc["library_id"]
        await self._chunks.delete_many({"document_id": doc_id, "user_id": user_id})
        await self._documents.delete_one({"_id": doc_id, "user_id": user_id})
        return library_id

    # ------------------------------------------------------------------
    # Chunks
    # ------------------------------------------------------------------

    async def upsert_chunks(
        self,
        user_id: str,
        document_id: str,
        library_id: str,
        chunks: list[dict],
    ) -> None:
        # Delete existing chunks for this document before inserting new ones
        await self._chunks.delete_many({"document_id": document_id, "user_id": user_id})

        if not chunks:
            return

        now = datetime.now(UTC)
        docs = [
            {
                "_id": str(uuid4()),
                "user_id": user_id,
                "document_id": document_id,
                "library_id": library_id,
                "created_at": now,
                **chunk,
            }
            for chunk in chunks
        ]
        await self._chunks.insert_many(docs)

    async def delete_chunks_for_document(self, document_id: str, user_id: str) -> int:
        result = await self._chunks.delete_many({"document_id": document_id, "user_id": user_id})
        return result.deleted_count

    async def vector_search(
        self,
        user_id: str,
        library_ids: list[str],
        query_vector: list[float],
        top_k: int = 5,
    ) -> list[dict]:
        pipeline = [
            {
                "$vectorSearch": {
                    "index": "knowledge_vector_index",
                    "path": "vector",
                    "queryVector": query_vector,
                    "numCandidates": top_k * 10,
                    "limit": top_k,
                    "filter": {
                        "user_id": user_id,
                        "library_id": {"$in": library_ids},
                    },
                },
            },
            {
                "$project": {
                    "text": 1,
                    "heading_path": 1,
                    "preroll_text": 1,
                    "document_id": 1,
                    "library_id": 1,
                    "chunk_index": 1,
                    "score": {"$meta": "vectorSearchScore"},
                },
            },
        ]
        cursor = self._chunks.aggregate(pipeline)
        return await cursor.to_list(length=top_k)

    # ------------------------------------------------------------------
    # DTO conversions
    # ------------------------------------------------------------------

    @staticmethod
    def to_library_dto(doc: dict) -> KnowledgeLibraryDto:
        return KnowledgeLibraryDto(
            id=doc["_id"],
            name=doc["name"],
            description=doc.get("description"),
            nsfw=doc.get("nsfw", False),
            document_count=doc.get("document_count", 0),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def to_document_dto(doc: dict) -> KnowledgeDocumentDto:
        return KnowledgeDocumentDto(
            id=doc["_id"],
            library_id=doc["library_id"],
            title=doc["title"],
            media_type=doc["media_type"],
            size_bytes=doc.get("size_bytes", 0),
            chunk_count=doc.get("chunk_count", 0),
            embedding_status=doc["embedding_status"],
            embedding_error=doc.get("embedding_error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
        )

    @staticmethod
    def to_document_detail_dto(doc: dict) -> KnowledgeDocumentDetailDto:
        return KnowledgeDocumentDetailDto(
            id=doc["_id"],
            library_id=doc["library_id"],
            title=doc["title"],
            media_type=doc["media_type"],
            size_bytes=doc.get("size_bytes", 0),
            chunk_count=doc.get("chunk_count", 0),
            embedding_status=doc["embedding_status"],
            embedding_error=doc.get("embedding_error"),
            created_at=doc["created_at"],
            updated_at=doc["updated_at"],
            content=doc["content"],
        )
