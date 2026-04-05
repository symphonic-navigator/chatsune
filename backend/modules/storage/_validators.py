from fastapi import HTTPException

# Supported image MIME types and their magic byte signatures
_IMAGE_SIGNATURES: dict[str, list[bytes]] = {
    "image/jpeg": [b"\xff\xd8\xff"],
    "image/png": [b"\x89PNG"],
    "image/gif": [b"GIF87a", b"GIF89a"],
    "image/webp": [b"RIFF"],  # also requires WEBP at offset 8
}

_ALLOWED_IMAGE_TYPES = set(_IMAGE_SIGNATURES.keys())

_MAX_IMAGE_BYTES = 10 * 1024 * 1024   # 10 MB
_MAX_TEXT_BYTES = 100 * 1024           # 100 KB
_MAX_ATTACHMENTS_PER_MESSAGE = 10


def _is_binary(data: bytes) -> bool:
    """Check if data contains null bytes in the first 8 KB."""
    return b"\x00" in data[:8192]


def _check_magic_bytes(data: bytes, media_type: str) -> bool:
    """Verify that the file's magic bytes match the declared MIME type."""
    sigs = _IMAGE_SIGNATURES.get(media_type)
    if not sigs:
        return False
    for sig in sigs:
        if data[: len(sig)] == sig:
            if media_type == "image/webp":
                return len(data) >= 12 and data[8:12] == b"WEBP"
            return True
    return False


def validate_upload(
    filename: str,
    data: bytes,
    content_type: str | None,
    current_quota_used: int,
    quota_limit: int,
    is_admin: bool = False,
) -> str:
    """Validate an uploaded file. Returns the resolved media type.

    Raises HTTPException on validation failure.
    """
    size = len(data)
    if size == 0:
        raise HTTPException(status_code=400, detail="Empty file")

    binary = _is_binary(data)

    if binary:
        if not content_type or content_type not in _ALLOWED_IMAGE_TYPES:
            raise HTTPException(
                status_code=415,
                detail="Unsupported binary format. Only JPEG, PNG, GIF, and WebP images are allowed.",
            )
        if not _check_magic_bytes(data, content_type):
            raise HTTPException(
                status_code=415,
                detail="File content does not match declared type",
            )
        if size > _MAX_IMAGE_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Image too large. Maximum size is {_MAX_IMAGE_BYTES // (1024 * 1024)} MB.",
            )
        media_type = content_type
    else:
        if size > _MAX_TEXT_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"Text file too large. Maximum size is {_MAX_TEXT_BYTES // 1024} KB.",
            )
        media_type = content_type or "text/plain"

    # Quota check (admins exempt)
    if not is_admin and (current_quota_used + size) > quota_limit:
        raise HTTPException(
            status_code=507,
            detail="Storage quota exceeded. Please delete some files first.",
        )

    return media_type


def validate_attachment_count(count: int) -> None:
    """Raise if too many attachments for a single message."""
    if count > _MAX_ATTACHMENTS_PER_MESSAGE:
        raise HTTPException(
            status_code=400,
            detail=f"Maximum {_MAX_ATTACHMENTS_PER_MESSAGE} attachments per message.",
        )
