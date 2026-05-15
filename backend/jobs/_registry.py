from backend.jobs._models import JobConfig, JobType
from backend.jobs.handlers._chatgpt_import_conversation import (
    handle_chatgpt_import_conversation,
)
from backend.jobs.handlers._chatgpt_import_memory_batch import (
    handle_chatgpt_import_memory_batch,
)
from backend.jobs.handlers._chatgpt_import_parse import handle_chatgpt_import_parse
from backend.jobs.handlers._memory_consolidation import handle_memory_consolidation
from backend.jobs.handlers._chat_compaction import handle_chat_compaction
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
        notify=True,
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
    JobType.CHATGPT_IMPORT_PARSE: JobConfig(
        handler=handle_chatgpt_import_parse,
        max_retries=1,
        retry_delay_seconds=30.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=600.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
    JobType.CHATGPT_IMPORT_CONVERSATION: JobConfig(
        handler=handle_chatgpt_import_conversation,
        max_retries=1,
        retry_delay_seconds=10.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=60.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
    # ``max_retries=0`` is deliberate: we want the user to drive resume
    # via the REST endpoint when a batch hits a terminal failure, not
    # silent auto-retry. The batch handler itself transitions the row
    # to ``paused`` and publishes a Paused event on any error.
    JobType.CHATGPT_IMPORT_MEMORY_BATCH: JobConfig(
        handler=handle_chatgpt_import_memory_batch,
        max_retries=0,
        retry_delay_seconds=0.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=1800.0,  # 30 minutes — multi-session batch
        reasoning_enabled=False,
        notify=False,
        notify_error=True,
    ),
    JobType.CHAT_COMPACTION: JobConfig(
        handler=handle_chat_compaction,
        max_retries=1,
        retry_delay_seconds=30.0,
        queue_timeout_seconds=3600.0,
        execution_timeout_seconds=120.0,
        reasoning_enabled=False,
        notify=True,
        notify_error=True,
    ),
}
