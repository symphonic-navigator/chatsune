"""Tool group registry — defines which tools exist and how they are grouped."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Literal, Protocol

if TYPE_CHECKING:
    from shared.dtos.inference import ToolDefinition


class ToolExecutor(Protocol):
    """Interface that server-side tool executors must satisfy."""

    async def execute(self, user_id: str, tool_name: str, arguments: dict) -> str:
        """Execute a tool call and return the result as a string."""
        ...


@dataclass(frozen=True)
class ToolGroup:
    id: str
    display_name: str
    description: str
    side: Literal["server", "client"]
    toggleable: bool
    tool_names: list[str]
    definitions: list[ToolDefinition] = field(default_factory=list)
    executor: ToolExecutor | None = None


def _build_groups() -> dict[str, ToolGroup]:
    """Build the tool group registry. Imported lazily to avoid circular imports."""
    from backend.modules.tools._executors import ArtefactToolExecutor, KnowledgeSearchExecutor, WebSearchExecutor
    from backend.modules.websearch import get_tool_definitions as ws_definitions
    from shared.dtos.inference import ToolDefinition

    ws_defs = ws_definitions()

    knowledge_defs = [
        ToolDefinition(
            name="knowledge_search",
            description="Search the user's knowledge base for relevant information. Use this when the user's question might relate to documents in their knowledge libraries.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query to find relevant knowledge chunks",
                    },
                },
                "required": ["query"],
            },
        ),
    ]

    return {
        "web_search": ToolGroup(
            id="web_search",
            display_name="Web Search",
            description="Search the web and fetch page content",
            side="server",
            toggleable=True,
            tool_names=[d.name for d in ws_defs],
            definitions=ws_defs,
            executor=WebSearchExecutor(),
        ),
        "knowledge_search": ToolGroup(
            id="knowledge_search",
            display_name="Knowledge",
            description="Search your knowledge libraries",
            side="server",
            toggleable=True,
            tool_names=["knowledge_search"],
            definitions=knowledge_defs,
            executor=KnowledgeSearchExecutor(),
        ),
        "artefacts": ToolGroup(
            id="artefacts",
            display_name="Artefacts",
            description="Create and manage artefacts (code, documents, diagrams) within the chat session",
            side="server",
            toggleable=True,
            tool_names=["create_artefact", "update_artefact", "read_artefact", "list_artefacts"],
            definitions=[
                ToolDefinition(
                    name="create_artefact",
                    description="Create a new artefact in the current chat session. Use for code files, documents, diagrams, or any substantial content that the user may want to view, copy, or iterate on.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "handle": {
                                "type": "string",
                                "description": "Unique identifier for the artefact within this session. Lowercase letters, digits, and hyphens only. E.g. 'main-py' or 'readme'.",
                            },
                            "title": {
                                "type": "string",
                                "description": "Human-readable title shown in the UI. E.g. 'main.py' or 'README'.",
                            },
                            "type": {
                                "type": "string",
                                "enum": ["markdown", "code", "html", "svg", "jsx", "mermaid"],
                                "description": (
                                    "The type of artefact. Use 'html' for full standalone HTML pages, "
                                    "'jsx' for React components, 'svg' for raw SVG markup, 'mermaid' for "
                                    "diagram syntax, 'markdown' for documents, and 'code' for everything "
                                    "else (set 'language' for syntax highlighting)."
                                ),
                            },
                            "content": {
                                "type": "string",
                                "description": "The full text content of the artefact.",
                            },
                            "language": {
                                "type": "string",
                                "description": "Programming or markup language for syntax highlighting. E.g. 'python', 'typescript'. Only relevant for type='code'.",
                            },
                        },
                        "required": ["handle", "title", "type", "content"],
                    },
                ),
                ToolDefinition(
                    name="update_artefact",
                    description="Update the content (and optionally the title) of an existing artefact. The previous version is saved so the user can undo.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "handle": {
                                "type": "string",
                                "description": "The handle of the artefact to update.",
                            },
                            "content": {
                                "type": "string",
                                "description": "The new full text content of the artefact.",
                            },
                            "title": {
                                "type": "string",
                                "description": "Optional new title. Omit to keep the existing title.",
                            },
                        },
                        "required": ["handle", "content"],
                    },
                ),
                ToolDefinition(
                    name="read_artefact",
                    description="Read the full content and metadata of an artefact by its handle.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "handle": {
                                "type": "string",
                                "description": "The handle of the artefact to read.",
                            },
                        },
                        "required": ["handle"],
                    },
                ),
                ToolDefinition(
                    name="list_artefacts",
                    description="List all artefacts in the current chat session with their handles, titles, types, and sizes.",
                    parameters={
                        "type": "object",
                        "properties": {},
                        "required": [],
                    },
                ),
            ],
            executor=ArtefactToolExecutor(),
        ),
    }


# Lazily initialised on first access.
_groups: dict[str, ToolGroup] | None = None


def get_groups() -> dict[str, ToolGroup]:
    global _groups
    if _groups is None:
        _groups = _build_groups()
    return _groups
