from datetime import datetime, UTC

import pytest

from backend.modules.images._repository import GeneratedImagesRepository
from backend.modules.images._models import GeneratedImageDocument


@pytest.fixture
async def repo(db):
    """`db` fixture is a Motor AsyncIOMotorDatabase from conftest."""
    r = GeneratedImagesRepository(db)
    await r.create_indexes()
    yield r
    await db["generated_images"].delete_many({})


def _make_doc(image_id: str, user_id: str = "u1", **overrides) -> GeneratedImageDocument:
    base = dict(
        id=image_id, user_id=user_id, blob_id=f"b_{image_id}",
        thumb_blob_id=f"t_{image_id}", prompt="x",
        model_id="grok-imagine", group_id="xai_imagine",
        connection_id="conn_a", config_snapshot={},
        width=1024, height=1024, content_type="image/jpeg",
        generated_at=datetime.now(UTC),
    )
    base.update(overrides)
    return GeneratedImageDocument(**base)


@pytest.mark.asyncio
async def test_insert_and_find(repo):
    doc = _make_doc("img_a")
    await repo.insert(doc)
    found = await repo.find_for_user(user_id="u1", image_id="img_a")
    assert found is not None
    assert found.id == "img_a"


@pytest.mark.asyncio
async def test_find_for_user_enforces_ownership(repo):
    await repo.insert(_make_doc("img_a", user_id="u1"))
    other = await repo.find_for_user(user_id="u2", image_id="img_a")
    assert other is None


@pytest.mark.asyncio
async def test_list_for_user_orders_by_generated_at_desc(repo):
    await repo.insert(_make_doc("img_a", generated_at=datetime(2026, 1, 1, tzinfo=UTC)))
    await repo.insert(_make_doc("img_b", generated_at=datetime(2026, 2, 1, tzinfo=UTC)))
    items = await repo.list_for_user(user_id="u1", limit=10, before=None)
    assert [i.id for i in items] == ["img_b", "img_a"]


@pytest.mark.asyncio
async def test_list_for_user_pagination_with_before(repo):
    t1 = datetime(2026, 1, 1, tzinfo=UTC)
    t2 = datetime(2026, 2, 1, tzinfo=UTC)
    await repo.insert(_make_doc("img_a", generated_at=t1))
    await repo.insert(_make_doc("img_b", generated_at=t2))
    items = await repo.list_for_user(user_id="u1", limit=10, before=t2)
    assert [i.id for i in items] == ["img_a"]


@pytest.mark.asyncio
async def test_delete_removes_document(repo):
    await repo.insert(_make_doc("img_a"))
    deleted = await repo.delete_for_user(user_id="u1", image_id="img_a")
    assert deleted is True
    assert await repo.find_for_user(user_id="u1", image_id="img_a") is None


@pytest.mark.asyncio
async def test_delete_all_for_user(repo):
    await repo.insert(_make_doc("img_a", user_id="u1"))
    await repo.insert(_make_doc("img_b", user_id="u1"))
    await repo.insert(_make_doc("img_c", user_id="u2"))
    deleted = await repo.delete_all_for_user(user_id="u1")
    assert deleted == 2
    remaining = await repo.list_for_user(user_id="u2", limit=10, before=None)
    assert len(remaining) == 1
