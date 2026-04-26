from datetime import datetime, UTC

from backend.modules.images._models import (
    GeneratedImageDocument,
    UserImageConfigDocument,
)


def test_generated_image_document_minimal_real_image():
    doc = GeneratedImageDocument(
        id="img_a", user_id="u1", blob_id="b1", thumb_blob_id="t1",
        prompt="a cat", model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={"tier": "normal"},
        width=1024, height=1024, content_type="image/jpeg",
        generated_at=datetime.now(UTC),
    )
    assert doc.moderated is False
    assert doc.tags == []


def test_generated_image_document_moderated_stub():
    doc = GeneratedImageDocument(
        id="img_b", user_id="u1",
        prompt="bad", model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={},
        moderated=True, moderation_reason="content_filter",
        generated_at=datetime.now(UTC),
    )
    assert doc.blob_id is None
    assert doc.thumb_blob_id is None
    assert doc.width is None
    assert doc.height is None


def test_user_image_config_document_required_fields():
    doc = UserImageConfigDocument(
        id="u1:conn_a:xai_imagine", user_id="u1",
        connection_id="conn_a", group_id="xai_imagine",
        config={"tier": "normal", "n": 4},
        updated_at=datetime.now(UTC),
    )
    assert doc.selected is False
