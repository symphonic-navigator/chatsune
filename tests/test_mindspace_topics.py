"""Mindspace Phase 1 — three new topic constants.

Spec §5.7 introduces:
- ``project.pinned.updated``
- ``chat.session.project.updated``
- ``user.recent_project_emojis.updated``

These are additive; the existing PROJECT_CREATED / PROJECT_UPDATED /
PROJECT_DELETED constants stay. The values must be unique across all
``Topics`` constants.
"""

from shared.topics import Topics, TopicDefinition


def _topic_value(t: object) -> str:
    """Topics in this module are either bare strings or
    ``TopicDefinition`` records — normalise to the underlying name."""
    if isinstance(t, TopicDefinition):
        return t.name
    return str(t)


def test_project_pinned_updated_topic_exists():
    assert hasattr(Topics, "PROJECT_PINNED_UPDATED")
    assert _topic_value(Topics.PROJECT_PINNED_UPDATED) == "project.pinned.updated"


def test_chat_session_project_updated_topic_exists():
    assert hasattr(Topics, "CHAT_SESSION_PROJECT_UPDATED")
    assert _topic_value(Topics.CHAT_SESSION_PROJECT_UPDATED) == "chat.session.project.updated"


def test_user_recent_project_emojis_updated_topic_exists():
    assert hasattr(Topics, "USER_RECENT_PROJECT_EMOJIS_UPDATED")
    assert _topic_value(Topics.USER_RECENT_PROJECT_EMOJIS_UPDATED) == "user.recent_project_emojis.updated"


def test_existing_project_topics_still_present():
    assert _topic_value(Topics.PROJECT_CREATED) == "project.created"
    assert _topic_value(Topics.PROJECT_UPDATED) == "project.updated"
    assert _topic_value(Topics.PROJECT_DELETED) == "project.deleted"


def test_all_topic_values_are_unique():
    values: list[str] = []
    for name, raw in vars(Topics).items():
        if name.startswith("_"):
            continue
        if isinstance(raw, str):
            values.append(raw)
        elif isinstance(raw, TopicDefinition):
            values.append(raw.name)
    assert len(values) == len(set(values)), (
        "Duplicate topic values: "
        f"{[v for v in values if values.count(v) > 1]}"
    )
