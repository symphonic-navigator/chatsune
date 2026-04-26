"""ImageService — central orchestrator for image generation, gallery, and config.

Coordinates between:
- ``LlmService``  (validate config, generate via adapter)
- ``BlobStore``   (persist raw bytes + thumbnails)
- ``GeneratedImagesRepository``  (image documents)
- ``UserImageConfigRepository``  (per-user active config)
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Literal

from backend.modules.images._models import GeneratedImageDocument, UserImageConfigDocument
from backend.modules.images._thumbnails import generate_thumbnail_jpeg
from backend.modules.llm._adapters._xai_http import drain_image_buffer
from shared.dtos.images import (
    ActiveImageConfigDto,
    ConnectionImageGroupsDto,
    GeneratedImageDetailDto,
    GeneratedImageSummaryDto,
    GeneratedImageResult,
    ImageRefDto,
    ModeratedRejection,
)

_log = logging.getLogger(__name__)


@dataclass
class ImageGenerationOutcome:
    """What ``generate_for_chat`` returns to the tool executor.

    ``image_refs`` contains one entry per successfully generated image.
    ``all_moderated`` is ``True`` when every requested image was blocked by
    upstream content moderation — the tool executor uses this to mark the
    tool call as failed so the LLM can rephrase.
    """

    image_refs: list[ImageRefDto] = field(default_factory=list)
    moderated_count: int = 0
    successful_count: int = 0
    llm_text_result: str = ""
    all_moderated: bool = False


def _format_llm_text(
    *,
    successful: int,
    moderated: int,
    refs: list[ImageRefDto],
) -> str:
    """Compose the text result that the LLM sees after a generate_images call.

    The final line is the Phase II hook that tells the model it can reference
    images by id in subsequent tool calls (image-to-image operations).
    """
    if successful == 0 and moderated > 0:
        return (
            f"All {moderated} requested image{'s were' if moderated != 1 else ' was'} "
            "filtered by content moderation. Try rephrasing the prompt."
        )

    total = successful + moderated
    lines: list[str] = []
    lines.append(f"Generated {successful} of {total} requested image{'s' if total != 1 else ''}.")
    if moderated > 0:
        lines.append(
            f"{moderated} image{'s were' if moderated != 1 else ' was'} filtered by content moderation."
        )
    lines.append("Images:")
    for i, ref in enumerate(refs, 1):
        lines.append(f"  {i}. id={ref.id} ({ref.width}x{ref.height}, {ref.model_id})")
    lines.append("Use the id values to reference these images in subsequent tool calls.")
    return "\n".join(lines)


class ImageService:
    """Central orchestrator for image generation, gallery, and config management.

    All dependencies are injected via ``__init__`` keyword arguments so that
    unit tests can pass mocks without touching the database or filesystem.
    """

    def __init__(
        self,
        *,
        llm_service,
        blob_store,
        gen_repo,
        cfg_repo,
    ) -> None:
        self._llm = llm_service
        self._blobs = blob_store
        self._gen = gen_repo
        self._cfg = cfg_repo

    # ------------------------------------------------------------------
    # Core generation
    # ------------------------------------------------------------------

    async def generate_for_chat(
        self,
        *,
        user_id: str,
        prompt: str,
        tool_call_id: str,
    ) -> ImageGenerationOutcome:
        """Generate images for a tool call and persist results.

        Returns an ``ImageGenerationOutcome`` describing the successful
        images (as ``ImageRefDto`` list) and a pre-formatted text string
        for the LLM to read as the tool result.

        Raises:
            LookupError: no active image configuration for ``user_id``.
        """
        _log.info(
            "image.generate_for_chat user_id=%s prompt_len=%d",
            user_id, len(prompt),
        )

        active = await self._cfg.get_active(user_id=user_id)
        if active is None:
            _log.warning("image.generate_for_chat user_id=%s no_active_config", user_id)
            raise LookupError("no active image configuration")

        # Validate the stored config against the group's typed schema.
        # The config may have a stale shape if the group schema changed.
        validated_config = await self._llm.validate_image_config(
            group_id=active.group_id,
            config=active.config,
        )

        items = await self._llm.generate_images(
            user_id=user_id,
            connection_id=active.connection_id,
            group_id=active.group_id,
            config=validated_config,
            prompt=prompt,
        )

        docs: list[GeneratedImageDocument] = []
        refs: list[ImageRefDto] = []
        moderated_count = 0
        successful_count = 0

        for item in items:
            if isinstance(item, ModeratedRejection):
                # Insert a stub document so the full batch is auditable.
                doc = GeneratedImageDocument(
                    id=f"img_{uuid.uuid4().hex[:12]}",
                    user_id=user_id,
                    prompt=prompt,
                    model_id="(moderated)",
                    group_id=active.group_id,
                    connection_id=active.connection_id,
                    config_snapshot=active.config,
                    moderated=True,
                    moderation_reason=item.reason,
                    generated_at=datetime.now(UTC),
                )
                docs.append(doc)
                moderated_count += 1
                continue

            # GeneratedImageResult — attempt to drain the adapter's byte buffer.
            assert isinstance(item, GeneratedImageResult)
            buf = drain_image_buffer(item.id)
            if buf is None:
                # Adapter promised a result but no bytes arrived; treat as moderated.
                _log.warning(
                    "image.generate_for_chat user_id=%s image_id=%s "
                    "reason=buffer_empty_treat_as_moderated",
                    user_id, item.id,
                )
                doc = GeneratedImageDocument(
                    id=item.id,
                    user_id=user_id,
                    prompt=prompt,
                    model_id=item.model_id,
                    group_id=active.group_id,
                    connection_id=active.connection_id,
                    config_snapshot=active.config,
                    moderated=True,
                    moderation_reason="adapter returned no bytes",
                    generated_at=datetime.now(UTC),
                )
                docs.append(doc)
                moderated_count += 1
                continue

            full_bytes, content_type = buf

            # Generate a thumbnail (always JPEG, max 256 px on longest edge).
            thumb_bytes = generate_thumbnail_jpeg(full_bytes, max_edge=256)

            # BlobStore requires real UUID file_ids — the adapter id (img_<hex>) is not valid.
            full_blob_id = str(uuid.uuid4())
            thumb_blob_id = str(uuid.uuid4())

            self._blobs.save(user_id, full_blob_id, full_bytes)
            self._blobs.save(user_id, thumb_blob_id, thumb_bytes)

            doc = GeneratedImageDocument(
                id=item.id,
                user_id=user_id,
                blob_id=full_blob_id,
                thumb_blob_id=thumb_blob_id,
                prompt=prompt,
                model_id=item.model_id,
                group_id=active.group_id,
                connection_id=active.connection_id,
                config_snapshot=active.config,
                width=item.width,
                height=item.height,
                content_type=content_type,
                generated_at=datetime.now(UTC),
            )
            docs.append(doc)

            # The URL uses the image_id (not blob_id); the HTTP route resolves
            # blob_id internally by looking up the document.
            ref = ImageRefDto(
                id=item.id,
                blob_url=f"/api/images/{item.id}/blob",
                thumb_url=f"/api/images/{item.id}/thumb",
                width=item.width,
                height=item.height,
                prompt=prompt,
                model_id=item.model_id,
                tool_call_id=tool_call_id,
            )
            refs.append(ref)
            successful_count += 1

        # Bulk-insert all documents (stubs + successes) in one round-trip.
        await self._gen.insert_many(docs)

        llm_text = _format_llm_text(
            successful=successful_count,
            moderated=moderated_count,
            refs=refs,
        )

        _log.info(
            "image.generate_for_chat user_id=%s successful=%d moderated=%d",
            user_id, successful_count, moderated_count,
        )

        return ImageGenerationOutcome(
            image_refs=refs,
            moderated_count=moderated_count,
            successful_count=successful_count,
            llm_text_result=llm_text,
            all_moderated=(successful_count == 0 and moderated_count > 0),
        )

    # ------------------------------------------------------------------
    # Gallery
    # ------------------------------------------------------------------

    async def list_user_images(
        self,
        *,
        user_id: str,
        limit: int = 50,
        before: datetime | None = None,
    ) -> list[GeneratedImageSummaryDto]:
        """Return paginated gallery summaries for ``user_id``.

        Moderated stubs are excluded from the gallery.
        """
        rows = await self._gen.list_for_user(user_id=user_id, limit=limit, before=before)
        return [
            GeneratedImageSummaryDto(
                id=r.id,
                thumb_url=f"/api/images/{r.id}/thumb",
                width=r.width,
                height=r.height,
                prompt=r.prompt,
                model_id=r.model_id,
                generated_at=r.generated_at,
            )
            for r in rows
            if not r.moderated
        ]

    async def get_image(
        self,
        *,
        user_id: str,
        image_id: str,
    ) -> GeneratedImageDetailDto | None:
        """Return full detail for one image owned by ``user_id``.

        Returns ``None`` for moderated stubs (treated as not found from the
        caller's perspective) and for images that do not exist or belong to
        another user.
        """
        doc = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if doc is None or doc.moderated:
            if doc is not None and doc.moderated:
                _log.warning(
                    "image.get_image user_id=%s image_id=%s not_found (moderated stub)",
                    user_id, image_id,
                )
            return None
        return GeneratedImageDetailDto(
            id=doc.id,
            thumb_url=f"/api/images/{doc.id}/thumb",
            blob_url=f"/api/images/{doc.id}/blob",
            width=doc.width,
            height=doc.height,
            prompt=doc.prompt,
            model_id=doc.model_id,
            generated_at=doc.generated_at,
            config_snapshot=doc.config_snapshot,
            connection_id=doc.connection_id,
            group_id=doc.group_id,
        )

    async def delete_image(
        self,
        *,
        user_id: str,
        image_id: str,
    ) -> bool:
        """Delete an image, its full blob, and its thumbnail.

        Returns ``True`` if deleted, ``False`` if not found or not owned.
        """
        doc = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if doc is None:
            _log.warning(
                "image.delete_image user_id=%s image_id=%s not_found",
                user_id, image_id,
            )
            return False

        # Delete blobs first; if they are already missing that's fine.
        if doc.blob_id:
            self._blobs.delete(user_id, doc.blob_id)
        if doc.thumb_blob_id:
            self._blobs.delete(user_id, doc.thumb_blob_id)

        return await self._gen.delete_for_user(user_id=user_id, image_id=image_id)

    async def stream_blob(
        self,
        *,
        user_id: str,
        image_id: str,
        kind: Literal["full", "thumb"],
    ) -> tuple[bytes, str] | None:
        """Load and return the raw bytes + content-type for an image or thumbnail.

        Returns ``None`` if the image does not exist, is moderated, or the
        blob is missing from the store.
        """
        doc = await self._gen.find_for_user(user_id=user_id, image_id=image_id)
        if doc is None or doc.moderated:
            return None

        if kind == "thumb":
            blob_id = doc.thumb_blob_id
            content_type = "image/jpeg"  # thumbnails are always JPEG
        else:
            blob_id = doc.blob_id
            content_type = doc.content_type or "image/jpeg"

        if blob_id is None:
            return None

        data = self._blobs.load(user_id, blob_id)
        if data is None:
            return None

        return data, content_type

    # ------------------------------------------------------------------
    # Config management
    # ------------------------------------------------------------------

    async def list_available_groups(
        self,
        *,
        user_id: str,
    ) -> list[ConnectionImageGroupsDto]:
        """Return all connections that support image generation for ``user_id``."""
        return await self._llm.list_image_groups(user_id=user_id)

    async def get_active_config(
        self,
        *,
        user_id: str,
    ) -> ActiveImageConfigDto | None:
        """Return the currently active image config for ``user_id``, or ``None``."""
        doc = await self._cfg.get_active(user_id=user_id)
        if doc is None:
            return None
        return ActiveImageConfigDto(
            connection_id=doc.connection_id,
            group_id=doc.group_id,
            config=doc.config,
        )

    async def set_active_config(
        self,
        *,
        user_id: str,
        connection_id: str,
        group_id: str,
        config: dict,
    ) -> ActiveImageConfigDto:
        """Validate, persist, and activate an image config for ``user_id``.

        Validates the config against the group's typed schema before writing
        so that stale or malformed configs are rejected immediately.

        Returns:
            The resulting ``ActiveImageConfigDto`` for the newly active config.
        """
        # Validate first — reject stale or malformed configs before touching the DB.
        await self._llm.validate_image_config(group_id=group_id, config=config)

        await self._cfg.upsert(
            user_id=user_id,
            connection_id=connection_id,
            group_id=group_id,
            config=config,
        )
        await self._cfg.set_active(
            user_id=user_id,
            connection_id=connection_id,
            group_id=group_id,
        )

        return ActiveImageConfigDto(
            connection_id=connection_id,
            group_id=group_id,
            config=config,
        )

    # ------------------------------------------------------------------
    # Right-to-be-forgotten
    # ------------------------------------------------------------------

    async def cascade_delete_user(self, *, user_id: str) -> int:
        """Delete all images (blobs + documents) and configs for ``user_id``.

        Used by the right-to-be-forgotten flow. Returns the count of image
        documents deleted (moderated stubs included).
        """
        _log.info("image.cascade_delete_user user_id=%s start", user_id)

        # Enumerate all documents so we can clean up blobs individually.
        docs = await self._gen.list_for_user(
            user_id=user_id,
            limit=10_000,
            before=None,
        )

        for doc in docs:
            if doc.blob_id:
                self._blobs.delete(user_id, doc.blob_id)
            if doc.thumb_blob_id:
                self._blobs.delete(user_id, doc.thumb_blob_id)

        deleted_docs = await self._gen.delete_all_for_user(user_id=user_id)
        await self._cfg.delete_all_for_user(user_id=user_id)

        _log.info(
            "image.cascade_delete_user user_id=%s deleted_images=%d",
            user_id, deleted_docs,
        )
        return deleted_docs
