"""Findings tool for saving key insights from conversations."""

from .base import BaseTool, ToolContext, ToolResult


class SaveFindingTool(BaseTool):
    """Save a key finding or insight to the user's workspace."""

    name = "save_finding"
    description = """Save a key finding or insight to the user's workspace.

Use this tool when the user asks you to:
- "save this", "write this up", "add to my findings", "save to workspace"
- "remember this", "note this down", "add this as a finding"
- "write that up and save it", "save a summary"

The finding should be a clear, concise summary of the key insight or information.
Include enough context that it makes sense on its own."""

    input_schema = {
        "type": "object",
        "properties": {
            "content": {
                "type": "string",
                "description": "The finding content - a clear, concise summary of the key insight. Should be self-contained and make sense on its own."
            },
            "note": {
                "type": "string",
                "description": "Optional additional context or note about the finding."
            }
        },
        "required": ["content"]
    }

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        content = params.get("content", "")
        note = params.get("note")

        if not content:
            return ToolResult(
                content="No content provided for finding.",
                success=False,
                metadata={"found": 0, "query": ""}
            )

        try:
            # Import here to avoid circular imports
            from api.database import Finding

            # Create and save the finding
            finding = Finding(
                project_id=context.project_id,
                thread_id=context.thread_id,
                content=content,
                note=note
            )
            context.db.add(finding)
            context.db.commit()

            result_message = f"Finding saved successfully with ID: {finding.id}"

            return ToolResult(
                content=result_message,
                metadata={
                    "found": 1,
                    "query": content[:50] + "..." if len(content) > 50 else content,
                    "saved": True,
                    "finding_id": finding.id,
                    "finding_content": finding.content
                }
            )

        except Exception as e:
            return ToolResult(
                content=f"Failed to save finding: {str(e)}",
                success=False,
                metadata={"found": 0, "error": str(e)}
            )
