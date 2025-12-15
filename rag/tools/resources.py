"""Resource-related tools for listing, inspecting, and reading workspace resources."""

import os
from dataclasses import dataclass

from .base import BaseTool, ToolContext, ToolResult


@dataclass
class ResourceInfo:
    """Information about a resource (matches the agent's ResourceInfo structure)."""
    name: str
    type: str  # "document", "website", "data_file", "image", "git_repository"
    status: str  # "ready", "pending", "indexing", "failed", etc.
    id: str | None = None
    summary: str | None = None
    columns: list[str] | None = None  # For data files
    row_count: int | None = None
    file_path: str | None = None
    dimensions: str | None = None  # For images


def _query_project_resources(context: ToolContext) -> list[ResourceInfo]:
    """Query resources for the current project from database.

    This ensures we always get fresh data from the database,
    not a stale snapshot from conversation start.
    """
    # Import here to avoid circular imports
    from api.database import Resource, ProjectResource

    db_resources = context.db.query(Resource).join(
        ProjectResource, ProjectResource.resource_id == Resource.id
    ).filter(
        ProjectResource.project_id == context.project_id
    ).all()

    resources = []
    for r in db_resources:
        # Skip failed resources
        if r.status.value == "failed":
            continue

        resource_info = ResourceInfo(
            name=r.filename or r.source,
            type=r.type.value,
            status=r.status.value,
            id=r.id,
            summary=r.summary,
            file_path=r.source,
        )

        # Add data file metadata if available
        if r.type.value == "data_file" and r.data_metadata:
            dm = r.data_metadata[0] if isinstance(r.data_metadata, list) else r.data_metadata
            if dm:
                resource_info.row_count = dm.row_count
                if dm.columns_json:
                    import json
                    try:
                        columns = json.loads(dm.columns_json)
                        resource_info.columns = [c.get("name", "") for c in columns]
                    except:
                        pass

        # Add image metadata if available
        if r.type.value == "image" and r.image_metadata:
            im = r.image_metadata[0] if isinstance(r.image_metadata, list) else r.image_metadata
            if im and im.width and im.height:
                resource_info.dimensions = f"{im.width}x{im.height}"

        resources.append(resource_info)

    return resources


def _find_resource_by_name(resources: list[ResourceInfo], name: str) -> ResourceInfo | None:
    """Find a resource by name (case-insensitive)."""
    for r in resources:
        if r.name == name or r.name.lower() == name.lower():
            return r
    return None


class ListResourcesTool(BaseTool):
    """List all resources in the current workspace."""

    name = "list_resources"
    description = """List all resources in the current workspace.

Use this tool when:
- User asks "what files do I have?", "what's in my workspace?", "show my documents"
- You need to know what resources are available before searching or analyzing
- User references "the document" or "my files" without being specific
- You want to help the user understand what they can work with

Returns a list of all resources with their type, status, and summary.

Status meanings:
- ✓ ready/indexed/analyzed/described: Fully processed, searchable
- ⏳ uploaded/extracting/indexing: Still processing
- ⚠ partial: File visible but semantic search unavailable (enrichment failed)
- ✗ failed: Unusable (extraction failed)"""

    input_schema = {
        "type": "object",
        "properties": {
            "type_filter": {
                "type": "string",
                "description": "Optional: filter by resource type ('document', 'data_file', 'image', 'website', 'git_repository')",
                "enum": ["document", "data_file", "image", "website", "git_repository"]
            },
            "status_filter": {
                "type": "string",
                "description": "Optional: filter by status",
                "enum": ["ready", "indexed", "analyzed", "described", "partial", "uploaded", "extracting", "indexing", "failed"]
            }
        },
        "required": []
    }

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        type_filter = params.get("type_filter")
        status_filter = params.get("status_filter")

        # Query fresh resources from database
        resources = _query_project_resources(context)

        # Apply filters
        filtered = resources
        if type_filter:
            filtered = [r for r in filtered if r.type == type_filter]
        if status_filter:
            filtered = [r for r in filtered if r.status == status_filter]

        if filtered:
            # Group by type for clear output
            by_type = {}
            for r in filtered:
                if r.type not in by_type:
                    by_type[r.type] = []
                by_type[r.type].append(r)

            result_parts = [f"Found {len(filtered)} resource(s) in your workspace:\n"]
            for rtype, rlist in by_type.items():
                result_parts.append(f"\n## {rtype.replace('_', ' ').title()}s ({len(rlist)})")
                for r in rlist:
                    # Status icons
                    ready_statuses = ("ready", "indexed", "analyzed", "described")
                    processing_statuses = ("pending", "uploaded", "extracting", "extracted", "indexing", "stored")
                    if r.status in ready_statuses:
                        status_icon = "✓"
                        status_note = ""
                    elif r.status == "partial":
                        status_icon = "⚠"
                        status_note = " [partial - searchable: no]"
                    elif r.status in processing_statuses:
                        status_icon = "⏳"
                        status_note = f" [{r.status}]"
                    else:
                        status_icon = "✗"
                        status_note = " [failed]"

                    summary_text = f": {r.summary[:100]}..." if r.summary and len(r.summary) > 100 else f": {r.summary}" if r.summary else ""
                    result_parts.append(f"  {status_icon} {r.name}{status_note}{summary_text}")

                    if r.type == "data_file" and r.columns:
                        cols = ", ".join(r.columns[:5])
                        if len(r.columns) > 5:
                            cols += f"... (+{len(r.columns) - 5} more)"
                        result_parts.append(f"    Columns: {cols}")
                        if r.row_count:
                            result_parts.append(f"    Rows: {r.row_count:,}")
                    elif r.type == "image" and r.dimensions:
                        result_parts.append(f"    Dimensions: {r.dimensions}")

            content = "\n".join(result_parts)
        else:
            if type_filter or status_filter:
                content = f"No resources found matching filters (type={type_filter or 'any'}, status={status_filter or 'any'})."
            else:
                content = "No resources in workspace yet. Upload documents, data files, or images to get started."

        return ToolResult(
            content=content,
            metadata={"found": len(filtered), "query": f"type={type_filter or 'all'}"}
        )


class GetResourceInfoTool(BaseTool):
    """Get detailed information about a specific resource."""

    name = "get_resource_info"
    description = """Get detailed information about a specific resource.

Use this tool when:
- User asks about a specific file ("tell me about sales.csv", "what's in the report?")
- You need metadata before analyzing (columns in a CSV, dimensions of an image)
- You want to understand a resource's content without searching

Returns detailed info: type, status, summary, and type-specific metadata (columns for data files, dimensions for images, etc.)."""

    input_schema = {
        "type": "object",
        "properties": {
            "resource_name": {
                "type": "string",
                "description": "The name of the resource to get info about"
            }
        },
        "required": ["resource_name"]
    }

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        resource_name = params.get("resource_name", "")

        # Query fresh resources from database
        resources = _query_project_resources(context)
        resource_info = _find_resource_by_name(resources, resource_name)

        if resource_info:
            info_parts = [
                f"## {resource_info.name}",
                f"- **Type:** {resource_info.type.replace('_', ' ').title()}",
                f"- **Status:** {resource_info.status}"
            ]
            if resource_info.summary:
                info_parts.append(f"- **Summary:** {resource_info.summary}")

            # Type-specific metadata
            if resource_info.type == "data_file":
                if resource_info.row_count:
                    info_parts.append(f"- **Rows:** {resource_info.row_count:,}")
                if resource_info.columns:
                    info_parts.append(f"- **Columns ({len(resource_info.columns)}):** {', '.join(resource_info.columns)}")
            elif resource_info.type == "image":
                if resource_info.dimensions:
                    info_parts.append(f"- **Dimensions:** {resource_info.dimensions}")

            content = "\n".join(info_parts)
            return ToolResult(
                content=content,
                metadata={"found": 1, "query": resource_name}
            )
        else:
            return ToolResult(
                content=f"Resource '{resource_name}' not found. Use list_resources to see available resources.",
                success=False,
                metadata={"found": 0, "query": resource_name}
            )


class ReadResourceTool(BaseTool):
    """Read the content or preview of a resource directly."""

    name = "read_resource"
    description = """Read the content or preview of a resource directly.

Use this tool when:
- User wants to see the actual content ("show me what's in the file")
- You need to preview data before running analysis
- search_documents isn't finding relevant content but you know the resource exists
- User asks "what does the beginning of X say?"

For documents: returns first N characters of text content
For data files: returns schema + sample rows
For images: returns the image for vision analysis (use view_image instead for questions)

This is a direct read - no semantic search involved."""

    input_schema = {
        "type": "object",
        "properties": {
            "resource_name": {
                "type": "string",
                "description": "The name of the resource to read"
            },
            "preview_lines": {
                "type": "integer",
                "description": "Number of lines/rows to preview (default: 50, max: 200)",
                "default": 50
            }
        },
        "required": ["resource_name"]
    }

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        resource_name = params.get("resource_name", "")
        preview_lines = min(params.get("preview_lines", 50), 200)

        # Query fresh resources from database
        resources = _query_project_resources(context)
        resource_info = _find_resource_by_name(resources, resource_name)

        if not resource_info:
            return ToolResult(
                content=f"Resource '{resource_name}' not found. Use list_resources to see available resources.",
                success=False,
                metadata={"found": 0, "query": resource_name}
            )

        if not resource_info.file_path:
            # Resource exists but no file path (e.g., website)
            info_text = f"'{resource_name}' ({resource_info.type}) has no local file to read directly."
            if resource_info.summary:
                info_text += f"\n\n**Summary:** {resource_info.summary}"
            info_text += "\n\nUse search_documents to find specific content within this resource."
            return ToolResult(
                content=info_text,
                metadata={"found": 1, "query": resource_name}
            )

        if not os.path.exists(resource_info.file_path):
            return ToolResult(
                content=f"Error: File for '{resource_name}' no longer exists on disk.",
                success=False,
                metadata={"found": 0, "query": resource_name}
            )

        try:
            if resource_info.type == "data_file":
                # For data files, show schema + sample rows
                import pandas as pd
                ext = os.path.splitext(resource_info.file_path)[1].lower()

                if ext == ".csv":
                    df = pd.read_csv(resource_info.file_path, nrows=preview_lines)
                elif ext in (".xlsx", ".xls"):
                    df = pd.read_excel(resource_info.file_path, nrows=preview_lines)
                elif ext == ".json":
                    df = pd.read_json(resource_info.file_path)
                    df = df.head(preview_lines)
                elif ext == ".parquet":
                    df = pd.read_parquet(resource_info.file_path)
                    df = df.head(preview_lines)
                else:
                    df = pd.read_csv(resource_info.file_path, nrows=preview_lines)

                # Build schema + preview
                schema = "\n".join([f"  - {col}: {df[col].dtype}" for col in df.columns])
                preview = df.head(min(10, preview_lines)).to_string()

                content = f"## {resource_name}\n\n**Schema ({len(df.columns)} columns):**\n{schema}\n\n**Preview ({len(df)} rows shown):**\n```\n{preview}\n```"

            elif resource_info.type == "image":
                # For images, return a note to use view_image instead
                content = f"'{resource_name}' is an image file. Use the view_image tool with a question to analyze its content."

            else:
                # For documents/text files, read the content
                with open(resource_info.file_path, "r", encoding="utf-8", errors="ignore") as f:
                    lines = []
                    for i, line in enumerate(f):
                        if i >= preview_lines:
                            break
                        lines.append(line.rstrip())
                    file_content = "\n".join(lines)

                content = f"## {resource_name}\n\n**Content preview ({len(lines)} lines):**\n```\n{file_content}\n```"

            return ToolResult(
                content=content,
                metadata={"found": 1, "query": resource_name}
            )

        except Exception as e:
            return ToolResult(
                content=f"Error reading '{resource_name}': {str(e)}",
                success=False,
                metadata={"found": 0, "query": resource_name}
            )
