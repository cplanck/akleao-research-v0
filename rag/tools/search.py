"""Search tools for document and web searches."""

import requests

from .base import BaseTool, ToolContext, ToolResult


class DocumentSearchTool(BaseTool):
    """Search the user's uploaded documents."""

    name = "search_documents"
    description = """Search the user's uploaded documents/workspace for relevant information.

ALWAYS use this tool when the user says any of:
- "search my documents", "search docs", "search workspace", "in my files"
- "what do my documents say about", "find in my uploads"
- "check my files", "look in my documents"

Also use for questions that might be answered by their uploaded documents."""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant document content. Be specific and use keywords."
            }
        },
        "required": ["query"]
    }

    requires = ["retriever"]

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        query = params.get("query", "")

        if not query:
            return ToolResult(
                content="No query provided.",
                success=False,
                metadata={"query": query, "found": 0}
            )

        try:
            # Perform the search using the retriever
            results = context.retriever.retrieve(
                query=query,
                namespaces=context.namespaces,
                top_k=5
            )

            # Format results
            content = self._format_results(results)

            # Include source info for the agent to emit
            sources = [
                {
                    "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                    "source": r.source,
                    "score": r.score,
                    "page_ref": r.metadata.get("page_ref"),
                    "page_numbers": r.metadata.get("page_numbers"),
                    "snippet": self._extract_snippet(r.content, 100),
                    "resource_id": r.metadata.get("resource_id"),
                    "line_start": r.metadata.get("line_start"),
                    "line_end": r.metadata.get("line_end"),
                    "github_url": self._build_github_url(r.metadata),
                }
                for r in results
            ]

            return ToolResult(
                content=content,
                metadata={"query": query, "found": len(results), "sources": sources}
            )
        except Exception as e:
            return ToolResult(
                content=f"Search failed: {str(e)}",
                success=False,
                metadata={"query": query, "found": 0}
            )

    def _format_results(self, results: list) -> str:
        """Format search results for the agent."""
        if not results:
            return "No relevant documents found."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] From {r.source}:\n{r.content}")
        return "\n\n---\n\n".join(parts)

    def _extract_snippet(self, content: str, max_length: int = 100) -> str:
        """Extract a meaningful snippet from content."""
        if not content:
            return ""

        content = content.strip()

        if len(content) <= max_length:
            return content

        # Try to find first sentence
        sentence_ends = ['. ', '.\n', '? ', '!\n']
        first_end = len(content)
        for end in sentence_ends:
            pos = content.find(end)
            if 0 < pos < first_end and pos <= max_length:
                first_end = pos + 1

        if first_end <= max_length:
            return content[:first_end].strip()

        # Fall back to truncating at word boundary
        truncated = content[:max_length]
        last_space = truncated.rfind(' ')
        if last_space > max_length // 2:
            truncated = truncated[:last_space]

        return truncated.strip() + "..."

    def _build_github_url(self, metadata: dict) -> str | None:
        """Build GitHub URL from metadata if available."""
        github_base_url = metadata.get("github_base_url")
        file_path = metadata.get("file_path")
        line_start = metadata.get("line_start")
        line_end = metadata.get("line_end")

        if not github_base_url or not file_path:
            return None

        github_url = f"{github_base_url}/{file_path}"
        if line_start and line_end:
            github_url += f"#L{line_start}-L{line_end}"
        elif line_start:
            github_url += f"#L{line_start}"

        return github_url


class WebSearchTool(BaseTool):
    """Search the internet for current information."""

    name = "search_web"
    description = """Search the internet for current information.

ALWAYS use this tool when the user says any of:
- "search the web", "search online", "search the internet", "google"
- "look up online", "find on the web", "what does the internet say"

Also use for questions about recent events, general knowledge not in documents, or when document search didn't find relevant results."""

    input_schema = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and use keywords."
            }
        },
        "required": ["query"]
    }

    requires = ["tavily_api_key"]

    def execute(self, params: dict, context: ToolContext) -> ToolResult:
        query = params.get("query", "")

        if not query:
            return ToolResult(
                content="No query provided.",
                success=False,
                metadata={"query": query, "found": 0}
            )

        if not context.tavily_api_key:
            return ToolResult(
                content="Web search is not configured.",
                success=False,
                metadata={"query": query, "found": 0}
            )

        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": context.tavily_api_key,
                    "query": query,
                    "search_depth": "basic",
                    "max_results": 5
                },
                timeout=10
            )
            response.raise_for_status()
            data = response.json()

            results = data.get("results", [])
            if not results:
                return ToolResult(
                    content="No results found.",
                    metadata={"query": query, "found": 0}
                )

            # Format results
            parts = []
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "Untitled")
                content = r.get("content", "")[:500]
                url = r.get("url", "")
                parts.append(f"[{i}] [{title}]({url})\n{content}")

            content = "\n\n---\n\n".join(parts) + "\n\nWhen citing these results, use markdown links like [text](url)."

            return ToolResult(
                content=content,
                metadata={"query": query, "found": len(results)}
            )

        except Exception as e:
            return ToolResult(
                content=f"Web search failed: {str(e)}",
                success=False,
                metadata={"query": query, "found": 0}
            )
