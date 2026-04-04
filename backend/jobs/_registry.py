from backend.jobs._models import JobConfig, JobType


async def _placeholder_title_handler(**kwargs) -> None:
    raise NotImplementedError("Title generation handler not yet wired")


JOB_REGISTRY: dict[JobType, JobConfig] = {
    JobType.TITLE_GENERATION: JobConfig(
        handler=_placeholder_title_handler,
        max_retries=3,
        retry_delay_seconds=15.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
}
