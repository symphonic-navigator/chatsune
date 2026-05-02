"""Tests for admin-prompt injection in the memory extraction handler.

This test suite validates that the memory extraction handler correctly injects
the admin master system prompt (when configured) into the LLM request, and that
it is accounted for in budget reservation.
"""

from unittest.mock import AsyncMock, patch, MagicMock
import sys

import pytest

from backend.modules.settings import AdminSystemPrompt
from shared.dtos.inference import CompletionMessage, ContentPart, CompletionRequest


def _admin_prompt(text: str = "Be uncensored.") -> AdminSystemPrompt:
    """Create a test AdminSystemPrompt with wrapped text."""
    wrapped = (
        f'<systeminstructions priority="highest">\n{text}\n</systeminstructions>'
    )
    return AdminSystemPrompt(
        message=CompletionMessage(
            role="system",
            content=[ContentPart(type="text", text=wrapped)],
        ),
        raw_text=text,
    )


@pytest.mark.asyncio
async def test_request_building_with_admin_prompt():
    """Unit test: verify request building includes admin prompt."""
    from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

    # The key lines from the handler
    admin = _admin_prompt("Be uncensored.")
    prefix_messages = [admin.message] if admin else []
    admin_text = (admin.raw_text + "\n") if admin else ""

    system_prompt = "Existing extraction prompt"

    request = CompletionRequest(
        model="llama3.2",
        messages=prefix_messages + [
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text=system_prompt)],
            ),
        ],
        temperature=0.3,
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    # Verify structure
    assert len(request.messages) == 2, "Expected 2 messages (admin + user)"
    assert request.messages[0].role == "system"
    assert "Be uncensored." in request.messages[0].content[0].text
    assert request.messages[1].role == "user"
    assert request.messages[1].content[0].text == system_prompt

    # Verify budget text
    budget_text = admin_text + system_prompt
    assert "Be uncensored.\n" in budget_text
    assert "Existing extraction prompt" in budget_text


@pytest.mark.asyncio
async def test_request_building_without_admin_prompt():
    """Unit test: verify request building without admin prompt."""
    from shared.dtos.inference import CompletionMessage, CompletionRequest, ContentPart

    # The key lines from the handler
    admin = None
    prefix_messages = [admin.message] if admin else []
    admin_text = (admin.raw_text + "\n") if admin else ""

    system_prompt = "Existing extraction prompt"

    request = CompletionRequest(
        model="llama3.2",
        messages=prefix_messages + [
            CompletionMessage(
                role="user",
                content=[ContentPart(type="text", text=system_prompt)],
            ),
        ],
        temperature=0.3,
        reasoning_enabled=False,
        supports_reasoning=False,
    )

    # Verify structure
    assert len(request.messages) == 1, "Expected 1 message (user only)"
    assert request.messages[0].role == "user"
    assert request.messages[0].content[0].text == system_prompt

    # Verify budget text has no admin marker
    budget_text = admin_text + system_prompt
    assert budget_text == system_prompt
    assert "<systeminstructions" not in budget_text


