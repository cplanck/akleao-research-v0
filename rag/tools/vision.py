"""Vision tool for analyzing images."""

import base64
import os
from pathlib import Path

from .base import BaseTool, ToolContext, ToolResult
from .resources import _query_project_resources, _find_resource_by_name


class ViewImageTool(BaseTool):
    """View and analyze an image file using vision."""

    name = "view_image"
    description = """View and analyze an image file using vision.

Use this tool when the user wants to:
- Describe what's in an image
- Extract text from a screenshot or diagram
- Analyze a chart or graph
- Compare visual elements
- Answer questions about image content

You MUST specify which image resource to view by filename."""

    input_schema = {
        "type": "object",
        "properties": {
            "resource_name": {
                "type": "string",
                "description": "The filename of the image to analyze (e.g., 'chart.png', 'screenshot.jpg')"
            },
            "question": {
                "type": "string",
                "description": "What to look for or analyze in the image (e.g., 'What does this chart show?', 'Extract the text from this screenshot')"
            }
        },
        "required": ["resource_name", "question"]
    }

    requires = ["anthropic_client"]

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        resource_name = params.get("resource_name", "")
        question = params.get("question", "Describe this image")

        if not resource_name:
            return ToolResult(
                content="No resource name provided.",
                success=False,
                metadata={"found": 0, "query": question}
            )

        # Query fresh resources from database
        resources = _query_project_resources(context)
        resource_info = _find_resource_by_name(resources, resource_name)

        if not resource_info:
            # List available images
            images = [r.name for r in resources if r.type == "image"]
            return ToolResult(
                content=f"Image '{resource_name}' not found. Available images: {', '.join(images) if images else 'none'}",
                success=False,
                metadata={"found": 0, "query": question}
            )

        if not resource_info.file_path:
            return ToolResult(
                content=f"Resource '{resource_name}' has no file path.",
                success=False,
                metadata={"found": 0, "query": question}
            )

        if not os.path.exists(resource_info.file_path):
            return ToolResult(
                content=f"Error: The file for '{resource_name}' no longer exists on disk. The resource may need to be re-uploaded.",
                success=False,
                metadata={"found": 0, "query": question}
            )

        try:
            # Read and encode image
            with open(resource_info.file_path, "rb") as f:
                image_data = base64.standard_b64encode(f.read()).decode("utf-8")

            # Determine media type
            ext = Path(resource_info.file_path).suffix.lower()
            media_types = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".gif": "image/gif",
                ".webp": "image/webp",
            }
            media_type = media_types.get(ext, "image/png")

            # Call Claude with vision
            vision_response = context.anthropic_client.messages.create(
                model="claude-sonnet-4-20250514",
                max_tokens=1024,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": image_data
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Filename: {resource_name}\n\nQuestion: {question}"
                        }
                    ]
                }]
            )

            vision_result = vision_response.content[0].text

            return ToolResult(
                content=f"Image analysis of {resource_name}:\n\n{vision_result}",
                metadata={
                    "found": 1,
                    "query": question[:50] + "..." if len(question) > 50 else question,
                    "resource": resource_name
                }
            )

        except Exception as e:
            return ToolResult(
                content=f"Error viewing {resource_name}: {str(e)}",
                success=False,
                metadata={
                    "found": 0,
                    "query": question[:50] + "..." if len(question) > 50 else question
                }
            )
