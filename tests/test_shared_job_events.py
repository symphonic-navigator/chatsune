from datetime import datetime, timezone


def test_job_started_event():
    from shared.events.jobs import JobStartedEvent

    event = JobStartedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    data = event.model_dump(mode="json")
    assert data["type"] == "job.started"
    assert data["job_id"] == "job-1"


def test_job_completed_event():
    from shared.events.jobs import JobCompletedEvent

    event = JobCompletedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.completed"


def test_job_failed_event():
    from shared.events.jobs import JobFailedEvent

    event = JobFailedEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        attempt=3,
        max_retries=3,
        error_message="Provider unavailable",
        recoverable=False,
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.failed"
    assert event.recoverable is False


def test_job_retry_event():
    from shared.events.jobs import JobRetryEvent

    event = JobRetryEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        attempt=1,
        next_retry_at=datetime(2026, 4, 4, 0, 0, 15, tzinfo=timezone.utc),
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.retry"
    assert event.attempt == 1


def test_job_expired_event():
    from shared.events.jobs import JobExpiredEvent

    event = JobExpiredEvent(
        job_id="job-1",
        job_type="title_generation",
        correlation_id="corr-1",
        waited_seconds=3600.0,
        timestamp=datetime(2026, 4, 4, tzinfo=timezone.utc),
    )
    assert event.type == "job.expired"


def test_topics_have_job_constants():
    from shared.topics import Topics

    assert Topics.JOB_STARTED == "job.started"
    assert Topics.JOB_COMPLETED == "job.completed"
    assert Topics.JOB_FAILED == "job.failed"
    assert Topics.JOB_RETRY == "job.retry"
    assert Topics.JOB_EXPIRED == "job.expired"
