"""
Tool Registry - Centralized configuration for tool display metadata.

This module provides a registry pattern for tools that makes it easy to:
1. Add new tools without changing core logic
2. Maintain consistent display across backend and frontend
3. Generate human-readable status messages for the UI
"""

from dataclasses import dataclass
from typing import Callable


@dataclass
class ToolDisplayConfig:
    """Display configuration for a tool."""
    id: str                    # Tool identifier (matches tool function name)
    display_name: str          # Human-readable name
    icon: str                  # Emoji icon for UI
    in_progress_template: str  # Template for "searching" state, e.g., "Searching for '{query}'"
    complete_template: str     # Template for success state, e.g., "Found {count} results"
    failed_template: str       # Template for no results/error state

    # Optional: Tool-specific result formatter
    result_formatter: Callable[[dict], dict] | None = None


# Registry of all tools with their display configurations
TOOL_REGISTRY: dict[str, ToolDisplayConfig] = {
    "search_documents": ToolDisplayConfig(
        id="search_documents",
        display_name="Document Search",
        icon="📄",
        in_progress_template="Searching documents for '{query}'",
        complete_template="Found {count} results in documents",
        failed_template="No relevant documents found for '{query}'"
    ),
    "search_web": ToolDisplayConfig(
        id="search_web",
        display_name="Web Search",
        icon="🌐",
        in_progress_template="Searching the web for '{query}'",
        complete_template="Found {count} web results",
        failed_template="No web results found for '{query}'"
    ),
    "analyze_data": ToolDisplayConfig(
        id="analyze_data",
        display_name="Data Analysis",
        icon="📊",
        in_progress_template="Analyzing '{resource}'",
        complete_template="Completed analysis of '{resource}'",
        failed_template="Failed to analyze '{resource}'"
    ),
    "view_image": ToolDisplayConfig(
        id="view_image",
        display_name="Image Analysis",
        icon="🖼️",
        in_progress_template="Analyzing image '{resource}'",
        complete_template="Analyzed '{resource}'",
        failed_template="Failed to analyze image '{resource}'"
    ),
    "save_finding": ToolDisplayConfig(
        id="save_finding",
        display_name="Save Finding",
        icon="💾",
        in_progress_template="Saving finding...",
        complete_template="Finding saved successfully",
        failed_template="Failed to save finding"
    ),
    # V3 Tools - Resource Awareness
    "list_resources": ToolDisplayConfig(
        id="list_resources",
        display_name="List Resources",
        icon="📋",
        in_progress_template="Listing workspace resources...",
        complete_template="Found {count} resource(s)",
        failed_template="No resources found"
    ),
    "get_resource_info": ToolDisplayConfig(
        id="get_resource_info",
        display_name="Get Resource Info",
        icon="ℹ️",
        in_progress_template="Getting info for '{query}'",
        complete_template="Retrieved info for '{query}'",
        failed_template="Resource '{query}' not found"
    ),
    "read_resource": ToolDisplayConfig(
        id="read_resource",
        display_name="Read Resource",
        icon="👁️",
        in_progress_template="Reading '{query}'",
        complete_template="Read '{query}' content",
        failed_template="Failed to read '{query}'"
    ),
}


def get_tool_display(tool_id: str) -> ToolDisplayConfig:
    """
    Get display config for a tool, with fallback for unknown tools.

    This allows the system to gracefully handle new tools before
    they're added to the registry.
    """
    if tool_id in TOOL_REGISTRY:
        return TOOL_REGISTRY[tool_id]

    # Fallback for unknown tools - generate reasonable defaults
    display_name = tool_id.replace("_", " ").title()
    return ToolDisplayConfig(
        id=tool_id,
        display_name=display_name,
        icon="⚙️",
        in_progress_template=f"Running {display_name.lower()}...",
        complete_template=f"{display_name} completed",
        failed_template=f"{display_name} failed"
    )


def format_tool_status(
    tool_id: str,
    stage: str,
    context: dict | None = None
) -> str:
    """
    Format a tool status message using the registry.

    Args:
        tool_id: Tool identifier (e.g., "search_documents")
        stage: One of "in_progress", "complete", or "failed"
        context: Dict with template variables like query, resource, count

    Returns:
        Formatted status string for display

    Example:
        >>> format_tool_status("search_web", "in_progress", {"query": "climate change"})
        "Searching the web for 'climate change'"

        >>> format_tool_status("search_web", "complete", {"count": 5})
        "Found 5 web results"
    """
    config = get_tool_display(tool_id)
    context = context or {}

    template_map = {
        "in_progress": config.in_progress_template,
        "complete": config.complete_template,
        "failed": config.failed_template,
    }

    template = template_map.get(stage, config.in_progress_template)

    # Safe formatting - only replace placeholders that exist in context
    try:
        # Handle missing keys gracefully
        formatted = template
        for key, value in context.items():
            placeholder = "{" + key + "}"
            if placeholder in formatted:
                formatted = formatted.replace(placeholder, str(value))

        # Remove any remaining unformatted placeholders
        import re
        formatted = re.sub(r"\{[^}]+\}", "", formatted)
        return formatted.strip()
    except Exception:
        return template


def register_tool(config: ToolDisplayConfig) -> None:
    """
    Register a new tool or update an existing one.

    This allows dynamic registration of tools at runtime,
    useful for plugins or experimental features.
    """
    TOOL_REGISTRY[config.id] = config


def get_all_tools() -> list[ToolDisplayConfig]:
    """Get all registered tools."""
    return list(TOOL_REGISTRY.values())
