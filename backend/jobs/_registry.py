from backend.jobs._models import JobConfig, JobType
from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation
from backend.jobs.handlers._memory_extraction import handle_memory_extraction
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
    JobType.MEMORY_EXTRACTION: JobConfig(
        handler=handle_memory_extraction,
        max_retries=2,
        retry_delay_seconds=30.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=120.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
    JobType.MEMORY_CONSOLIDATION: JobConfig(
        handler=handle_memory_consolidation,
        max_retries=2,
        retry_delay_seconds=60.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=180.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
}
