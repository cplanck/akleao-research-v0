"""Tool system for the RAG agent.

This module provides a clean, extensible tool architecture where each tool is
a self-contained class with its own schema, implementation, and direct database/API access.
"""

from .base import BaseTool, ToolContext, ToolResult
from .registry import ToolRegistry, get_registry
from .executor import ToolExecutor, ToolEvent

# Individual tools (for direct access if needed)
from .resources import ListResourcesTool, GetResourceInfoTool, ReadResourceTool
from .search import DocumentSearchTool, WebSearchTool
from .findings import SaveFindingTool
from .data import AnalyzeDataTool
from .vision import ViewImageTool

__all__ = [
    # Core classes
    "BaseTool",
    "ToolContext",
    "ToolResult",
    "ToolRegistry",
    "ToolExecutor",
    "ToolEvent",
    "get_registry",
    # Tools
    "ListResourcesTool",
    "GetResourceInfoTool",
    "ReadResourceTool",
    "DocumentSearchTool",
    "WebSearchTool",
    "SaveFindingTool",
    "AnalyzeDataTool",
    "ViewImageTool",
]
