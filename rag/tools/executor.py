"""Tool executor for dispatching tool calls and handling events."""

from typing import Iterator
from dataclasses import dataclass

from .base import ToolContext, ToolResult
from .registry import ToolRegistry


@dataclass
class ToolEvent:
    """Event emitted during tool execution."""
    type: str  # "tool_call" or "tool_result"
    data: dict


class ToolExecutor:
    """Executes tools and yields events.

    Handles:
    - Tool dispatch by name
    - Event emission (tool_call, tool_result)
    - Error handling
    - Tool result formatting for Claude
    """

    def __init__(self, registry: ToolRegistry, context: ToolContext):
        self.registry = registry
        self.context = context

    def execute(
        self,
        tool_name: str,
        tool_use_id: str,
        params: dict
    ) -> tuple[str, list[ToolEvent], dict]:
        """Execute a tool and return result with events.

        Args:
            tool_name: Name of the tool to execute
            tool_use_id: Claude's tool_use_id for linking result
            params: Parameters from Claude

        Returns:
            Tuple of (result_content, events_list, metadata)
            metadata contains full tool result metadata including sources for search
        """
        events = []

        # Get tool
        tool = self.registry.get(tool_name)
        if not tool:
            error_content = f"Unknown tool: {tool_name}"
            events.append(ToolEvent("tool_result", {
                "tool": tool_name,
                "error": error_content
            }))
            return error_content, events, {}

        # Emit tool_call event
        call_event_data = {
            "tool": tool_name,
            **self._extract_event_data(tool_name, params)
        }
        events.append(ToolEvent("tool_call", call_event_data))

        # Execute tool
        try:
            result = tool.execute(params, self.context)

            # Emit tool_result event (exclude large data like sources)
            result_event_data = {
                "tool": tool_name,
                **{k: v for k, v in result.metadata.items() if k != "sources"}
            }
            if not result.success:
                result_event_data["error"] = True
            events.append(ToolEvent("tool_result", result_event_data))

            return result.content, events, result.metadata

        except Exception as e:
            error_content = f"Tool execution failed: {str(e)}"
            events.append(ToolEvent("tool_result", {
                "tool": tool_name,
                "error": str(e)
            }))
            return error_content, events, {}

    def _extract_event_data(self, tool_name: str, params: dict) -> dict:
        """Extract relevant data for tool_call event based on tool type."""
        if tool_name in ("search_documents", "search_web"):
            return {"query": params.get("query", "")}
        elif tool_name == "list_resources":
            type_filter = params.get("type_filter")
            status_filter = params.get("status_filter")
            return {"query": f"type={type_filter or 'all'}, status={status_filter or 'all'}"}
        elif tool_name == "get_resource_info":
            return {"query": params.get("resource_name", "")}
        elif tool_name == "read_resource":
            return {"query": params.get("resource_name", "")}
        elif tool_name == "analyze_data":
            return {
                "resource": params.get("resource_name", ""),
                "query": params.get("query", "")
            }
        elif tool_name == "view_image":
            return {
                "resource": params.get("resource_name", ""),
                "query": params.get("question", "")
            }
        elif tool_name == "save_finding":
            return {"content_preview": params.get("content", "")[:100]}
        return {}

    def format_tool_result_for_claude(
        self,
        tool_use_id: str,
        content: str
    ) -> dict:
        """Format a tool result for Claude's messages API."""
        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content
        }
