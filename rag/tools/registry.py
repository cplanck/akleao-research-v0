"""Tool registry for managing available tools."""

from typing import Type
from .base import BaseTool, ToolContext


class ToolRegistry:
    """Registry for tool discovery and management.

    Handles:
    - Tool registration
    - Tool lookup by name
    - Generating schemas for Claude's API (filtered by availability)
    """

    def __init__(self):
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance."""
        self._tools[tool.name] = tool

    def register_class(self, tool_class: Type[BaseTool]) -> None:
        """Register a tool by instantiating its class."""
        tool = tool_class()
        self.register(tool)

    def get(self, name: str) -> BaseTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_tools(self) -> list[str]:
        """List all registered tool names."""
        return list(self._tools.keys())

    def get_available_tools(self, context: ToolContext) -> list[BaseTool]:
        """Get all tools available in the given context."""
        return [
            tool for tool in self._tools.values()
            if tool.is_available(context)
        ]

    def get_schemas(self, context: ToolContext) -> list[dict]:
        """Get schemas for all available tools (for Claude's API)."""
        return [
            tool.get_schema()
            for tool in self.get_available_tools(context)
        ]


# Global registry instance
_global_registry: ToolRegistry | None = None


def get_registry() -> ToolRegistry:
    """Get the global tool registry, creating it if needed."""
    global _global_registry
    if _global_registry is None:
        _global_registry = ToolRegistry()
        _register_all_tools(_global_registry)
    return _global_registry


def _register_all_tools(registry: ToolRegistry) -> None:
    """Register all built-in tools."""
    # Import here to avoid circular imports
    from .resources import ListResourcesTool, GetResourceInfoTool, ReadResourceTool
    from .search import DocumentSearchTool, WebSearchTool
    from .findings import SaveFindingTool
    from .data import AnalyzeDataTool
    from .vision import ViewImageTool

    # Register all tools
    registry.register(ListResourcesTool())
    registry.register(GetResourceInfoTool())
    registry.register(ReadResourceTool())
    registry.register(DocumentSearchTool())
    registry.register(WebSearchTool())
    registry.register(SaveFindingTool())
    registry.register(AnalyzeDataTool())
    registry.register(ViewImageTool())
