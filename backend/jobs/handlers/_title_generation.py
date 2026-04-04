import logging

from backend.jobs._models import JobConfig, JobEntry
from backend.modules.llm import ContentDelta, StreamDone, StreamError
from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

_log = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 64

_SYSTEM_PROMPT = (
    "Generate a short, descriptive title for the following conversation. "
    "Respond with ONLY the title — no quotes, no explanation, no punctuation at the end. "
    "Maximum 60 characters. Use the language of the conversation."
)


def _clean_title(raw: str) -> str:
    """Strip quotes, whitespace, trailing punctuation, and truncate."""
    title = raw.strip().strip("\"'").strip()
    if title.endswith("."):
        title = title[:-1].strip()
    if len(title) > _MAX_TITLE_LENGTH:
        truncated = title[:_MAX_TITLE_LENGTH]
        last_space = truncated.rfind(" ")
        if last_space > _MAX_TITLE_LENGTH // 2:
            title = truncated[:last_space]
        else:
            title = truncated
    return title


async def handle_title_generation(
    job: JobEntry,
    config: JobConfig,
    redis,
    event_bus,
) -> None:
    """Generate a title for a chat session using the same model as the chat."""
    # Deferred imports to avoid circular dependency (chat -> jobs -> handler -> chat).
    from backend.modules.chat import update_session_title
    from backend.modules.llm import stream_completion as llm_stream_completion

    provider_id, model_slug = job.model_unique_id.split(":", 1)
    messages_data = job.payload.get("messages", [])

    messages = [
        CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=_SYSTEM_PROMPT)],
        ),
    ]
    for msg in messages_data:
        messages.append(CompletionMessage(
            role=msg["role"],
            content=[ContentPart(type="text", text=msg["content"])],
        ))

    request = CompletionRequest(
        model=model_slug,
        messages=messages,
        temperature=0.3,
        reasoning_enabled=False,
    )

    full_content = ""
    async for event in llm_stream_completion(job.user_id, provider_id, request):
        match event:
            case ContentDelta(delta=delta):
                full_content += delta
            case StreamDone():
                break
            case StreamError() as err:
                raise RuntimeError(
                    f"Title generation failed: {err.error_code} — {err.message}"
                )

    title = _clean_title(full_content)
    if not title:
        _log.warning("Title generation produced empty result for job %s", job.id)
        return

    await update_session_title(
        session_id=job.payload["session_id"],
        title=title,
        user_id=job.user_id,
        correlation_id=job.correlation_id,
    )
    _log.info("Generated title '%s' for session %s", title, job.payload["session_id"])
