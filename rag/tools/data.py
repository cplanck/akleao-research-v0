"""Data analysis tool for querying CSV, Excel, and JSON files."""

import os

from .base import BaseTool, ToolContext, ToolResult
from .resources import _query_project_resources, _find_resource_by_name


class AnalyzeDataTool(BaseTool):
    """Analyze a CSV, Excel, or JSON data file."""

    name = "analyze_data"
    description = """Analyze a CSV, Excel, or JSON data file.

Use this tool when the user wants to:
- Query data from a specific file (e.g., "What are the top 10 customers?")
- Calculate statistics (e.g., "What's the average price?")
- Filter or aggregate data (e.g., "Show sales by region")
- Explore data (e.g., "What columns are in this file?")

You MUST specify which resource to analyze by filename.
The query should describe what analysis to perform in natural language."""

    input_schema = {
        "type": "object",
        "properties": {
            "resource_name": {
                "type": "string",
                "description": "The filename of the data resource to analyze (e.g., 'sales_data.csv', 'inventory.xlsx')"
            },
            "query": {
                "type": "string",
                "description": "Natural language description of the analysis to perform (e.g., 'top 10 customers by total sales', 'average price by category')"
            }
        },
        "required": ["resource_name", "query"]
    }

    requires = ["anthropic_api_key"]

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        resource_name = params.get("resource_name", "")
        query = params.get("query", "")

        if not resource_name:
            return ToolResult(
                content="No resource name provided.",
                success=False,
                metadata={"found": 0, "query": query}
            )

        if not query:
            return ToolResult(
                content="No query provided.",
                success=False,
                metadata={"found": 0, "query": ""}
            )

        # Query fresh resources from database
        resources = _query_project_resources(context)
        resource_info = _find_resource_by_name(resources, resource_name)

        if not resource_info:
            # List available data files
            data_files = [r.name for r in resources if r.type == "data_file"]
            return ToolResult(
                content=f"Resource '{resource_name}' not found. Available data files: {', '.join(data_files) if data_files else 'none'}",
                success=False,
                metadata={"found": 0, "query": query}
            )

        if not resource_info.file_path:
            return ToolResult(
                content=f"Resource '{resource_name}' has no file path.",
                success=False,
                metadata={"found": 0, "query": query}
            )

        if not os.path.exists(resource_info.file_path):
            return ToolResult(
                content=f"Error: The file for '{resource_name}' no longer exists on disk. The resource may need to be re-uploaded.",
                success=False,
                metadata={"found": 0, "query": query}
            )

        try:
            from rag.data_analysis import DataAnalyzer

            analyzer = DataAnalyzer(api_key=context.anthropic_api_key)
            result = analyzer.analyze(resource_info.file_path, query)

            return ToolResult(
                content=f"Analysis of {resource_name}:\n\n{result}",
                metadata={
                    "found": 1,
                    "query": query[:50] + "..." if len(query) > 50 else query,
                    "resource": resource_name
                }
            )

        except Exception as e:
            return ToolResult(
                content=f"Error analyzing {resource_name}: {str(e)}",
                success=False,
                metadata={
                    "found": 0,
                    "query": query[:50] + "..." if len(query) > 50 else query
                }
            )
