"""Tool executor for the ``generate_image`` tool.

This module is intentionally separate from ``_service.py`` so the tool
registry can import it without pulling in the full service graph.
"""

from __future__ import annotations

import logging

from shared.dtos.inference import ToolDefinition

_log = logging.getLogger(__name__)

# Context injection convention for image generation:
#
# The chat orchestrator passes ``tool_call_id`` as a separate keyword
# argument to ``execute_tool()``, which routes it to the client-tool
# dispatcher or the executor's ``execute()`` method depending on group
# side.  Server-side executors currently receive only
# ``(user_id, tool_name, arguments)`` — ``tool_call_id`` is NOT in the
# Protocol signature.
#
# ``generate_image`` needs the ``tool_call_id`` so it can stamp the
# resulting ``ImageRefDto`` records (used by the gallery and Phase II
# image-to-image operations).  Until the ``ToolExecutor`` Protocol is
# widened to pass ``tool_call_id`` natively (Task 15 work), the
# orchestrator must inject it into ``arguments["__tool_call_id__"]``
# before calling ``execute_tool()``.  The double-underscore prefix
# follows the existing pattern of private dispatch keys (``_session_id``,
# ``_correlation_id``, etc.) — the leading ``__`` signals that this key
# is injected by infrastructure, not supplied by the LLM.
#
# Task 15 should update ``_orchestrator._make_tool_executor`` to inject
# ``arguments["__tool_call_id__"] = tool_call_id`` for ``generate_image``
# calls, mirroring the existing ``_session_id`` injections.


class ImageGenerationToolExecutor:
    """Dispatches ``generate_image`` tool calls to ``ImageService``."""

    def __init__(self, image_service) -> None:
        self._svc = image_service

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        """Execute a ``generate_image`` tool call and return an LLM-readable result."""
        if tool_name != "generate_image":
            raise ValueError(
                f"ImageGenerationToolExecutor cannot handle tool '{tool_name}'"
            )

        prompt: str = arguments.get("prompt", "") or ""
        if not prompt.strip():
            return "Error: prompt is required and must be a non-empty string."

        tool_call_id: str = arguments.get("__tool_call_id__", "")

        _log.info(
            "image.tool_executor.execute user_id=%s prompt_len=%d tool_call_id=%s",
            user_id, len(prompt), tool_call_id or "(none)",
        )

        try:
            from backend.modules.images._service import ImageService  # noqa: F401 (type hint only)
            outcome = await self._svc.generate_for_chat(
                user_id=user_id,
                prompt=prompt,
                tool_call_id=tool_call_id,
            )
        except LookupError:
            return (
                "Error: image generation is not configured. "
                "The user needs to set up an image-capable connection "
                "and select an active image configuration."
            )
        except Exception as exc:
            _log.exception(
                "image.tool_executor.execute failed user_id=%s tool_call_id=%s: %s",
                user_id, tool_call_id, exc,
            )
            return f"Error: image generation failed: {type(exc).__name__}"

        return outcome.llm_text_result

    @staticmethod
    def tool_definition() -> ToolDefinition:
        """Return the ``ToolDefinition`` for the ``generate_image`` tool."""
        return ToolDefinition(
            name="generate_image",
            description=(
                "Generate one or more images from a text prompt. "
                "The user has pre-configured the model, count, and image "
                "dimensions; you only choose the prompt. Be descriptive — "
                "a good prompt has subject, style, lighting, and composition cues."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "prompt": {
                        "type": "string",
                        "description": (
                            "A detailed text description of the image(s) to generate. "
                            "Include subject, style, lighting, and composition cues "
                            "for best results."
                        ),
                    },
                },
                "required": ["prompt"],
            },
        )
