from shared.topics import Topics


def test_project_topics_exist():
    assert Topics.PROJECT_CREATED == "project.created"
    assert Topics.PROJECT_UPDATED == "project.updated"
    assert Topics.PROJECT_DELETED == "project.deleted"
