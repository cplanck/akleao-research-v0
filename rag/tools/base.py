"""Base classes for the tool system."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolContext:
    """Context passed to every tool execution.

    Contains everything a tool might need to execute, including
    database access, project info, and API clients.
    """
    # Database session for queries
    db: Any  # Session type from sqlalchemy.orm

    # Project context
    project_id: str
    thread_id: str

    # For document search
    retriever: Any = None  # Retriever instance
    namespaces: list[str] = field(default_factory=list)

    # For vision and LLM calls
    anthropic_client: Any = None
    anthropic_api_key: str | None = None

    # For web search
    tavily_api_key: str | None = None


@dataclass
class ToolResult:
    """Standardized result from tool execution."""
    content: str  # Result text for Claude
    success: bool = True
    metadata: dict = field(default_factory=dict)  # For events (count, query, etc.)


class BaseTool(ABC):
    """Abstract base class for all tools.

    Each tool must define:
    - name: The tool name used by Claude
    - description: Detailed description of what the tool does
    - input_schema: JSON Schema for the tool's parameters
    - execute(): The implementation

    Tools also specify:
    - requires: List of ToolContext attributes needed (for conditional availability)
    """

    name: str
    description: str
    input_schema: dict
    requires: list[str] = []  # e.g., ["retriever"] for document search

    @abstractmethod
    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        """Execute the tool with given parameters and context.

        Args:
            params: Dictionary of input parameters from Claude
            context: ToolContext with DB, project info, etc.

        Returns:
            ToolResult with content for Claude and metadata for events
        """
        pass

    def get_schema(self) -> dict:
        """Return the tool schema for Claude's API."""
        return {
            "name": self.name,
            "description": self.description,
            "input_schema": self.input_schema
        }

    def is_available(self, context: ToolContext) -> bool:
        """Check if this tool is available given the context.

        Override this method for custom availability logic.
        Default implementation checks that all required attributes exist.
        """
        for attr in self.requires:
            if not getattr(context, attr, None):
                return False
        return True
