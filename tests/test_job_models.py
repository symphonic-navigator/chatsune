from datetime import datetime, timezone


def test_job_entry_serialisation():
    from backend.jobs._models import JobEntry, JobType

    entry = JobEntry(
        id="job-1",
        job_type=JobType.TITLE_GENERATION,
        user_id="user-1",
        model_unique_id="ollama_cloud:llama3.2",
        payload={"session_id": "sess-1"},
        correlation_id="corr-1",
        created_at=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )

    data = entry.model_dump(mode="json")
    assert data["job_type"] == "title_generation"
    assert data["attempt"] == 0

    roundtrip = JobEntry.model_validate(data)
    assert roundtrip.id == "job-1"
    assert roundtrip.model_unique_id == "ollama_cloud:llama3.2"


def test_job_config_defaults():
    from backend.jobs._models import JobConfig

    config = JobConfig(handler=lambda: None)
    assert config.max_retries == 3
    assert config.retry_delay_seconds == 15.0
    assert config.queue_timeout_seconds == 3600.0
    assert config.execution_timeout_seconds == 300.0
    assert config.reasoning_enabled is False
    assert config.notify is False
    assert config.notify_error is False


def test_job_config_custom_values():
    from backend.jobs._models import JobConfig

    config = JobConfig(
        handler=lambda: None,
        max_retries=5,
        retry_delay_seconds=180.0,
        execution_timeout_seconds=600.0,
        notify=True,
    )
    assert config.max_retries == 5
    assert config.retry_delay_seconds == 180.0
    assert config.execution_timeout_seconds == 600.0
    assert config.notify is True


def test_registry_contains_title_generation():
    from backend.jobs._models import JobType
    from backend.jobs._registry import JOB_REGISTRY

    assert JobType.TITLE_GENERATION in JOB_REGISTRY
    config = JOB_REGISTRY[JobType.TITLE_GENERATION]
    assert config.max_retries == 3
    assert config.retry_delay_seconds == 15.0
    assert config.execution_timeout_seconds == 60.0
    assert config.reasoning_enabled is False
    assert config.notify is False
    assert config.notify_error is True
