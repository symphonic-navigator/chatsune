from datetime import datetime, timezone

from shared.events.jobs import JobStartedEvent, JobRetryEvent


def test_job_started_event_has_notify_and_persona_id_defaults():
    """New optional fields default to backwards-compatible values."""
    ev = JobStartedEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.notify is True
    assert ev.persona_id is None


def test_job_started_event_accepts_notify_and_persona_id():
    ev = JobStartedEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        timestamp=datetime.now(timezone.utc),
        notify=False,
        persona_id="persona-42",
    )
    assert ev.notify is False
    assert ev.persona_id == "persona-42"


def test_job_retry_event_has_notify_default():
    ev = JobRetryEvent(
        job_id="job-1",
        job_type="memory_extraction",
        correlation_id="corr-1",
        attempt=1,
        next_retry_at=datetime.now(timezone.utc),
        timestamp=datetime.now(timezone.utc),
    )
    assert ev.notify is True
