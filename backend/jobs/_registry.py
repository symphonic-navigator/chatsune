from backend.jobs._models import JobConfig, JobType
from backend.jobs.handlers._title_generation import handle_title_generation

JOB_REGISTRY: dict[JobType, JobConfig] = {
    JobType.TITLE_GENERATION: JobConfig(
        handler=handle_title_generation,
        max_retries=3,
        retry_delay_seconds=15.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
}
