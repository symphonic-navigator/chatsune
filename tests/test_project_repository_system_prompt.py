"""Tests for ProjectRepository.get_system_prompt — projection-only fetch
of the per-project Custom Instructions added by Mindspace project-CI."""

import pytest_asyncio

from backend.modules.project import ProjectRepository


@pytest_asyncio.fixture
async def repo(client, db):
    """The ``client`` fixture wires up the app + clean DB; ``db`` gives
    us a Motor handle bound to the test database."""
    return ProjectRepository(db)


async def test_get_system_prompt_returns_value_for_owner(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="be helpful",
    )
    result = await repo.get_system_prompt(proj["_id"], "u-a")
    assert result == "be helpful"


async def test_get_system_prompt_returns_none_for_missing(repo):
    result = await repo.get_system_prompt("does-not-exist", "u-a")
    assert result is None


async def test_get_system_prompt_returns_none_for_wrong_owner(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="secret",
    )
    result = await repo.get_system_prompt(proj["_id"], "u-b")
    assert result is None


async def test_get_system_prompt_returns_none_when_unset(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
    )
    result = await repo.get_system_prompt(proj["_id"], "u-a")
    assert result is None


async def test_to_dto_round_trips_system_prompt(repo):
    proj = await repo.create(
        user_id="u-a", title="P", emoji=None, description=None, nsfw=False,
        system_prompt="round trip",
    )
    dto = ProjectRepository.to_dto(proj)
    assert dto.system_prompt == "round trip"
