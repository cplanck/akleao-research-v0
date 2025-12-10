"""Agentic LLM module - conversational assistant with tool use."""

import os
import requests
from typing import Iterator, Callable, Optional
from dataclasses import dataclass
from anthropic import Anthropic

from .retriever import Retriever, RetrievalResult

# Beta header for interleaved thinking with tool use
INTERLEAVED_THINKING_BETA = "interleaved-thinking-2025-05-14"


@dataclass
class AgentResponse:
    """Response from the agent."""
    content: str
    sources: list[RetrievalResult]
    used_search: bool


# Tool definitions for Claude
DOCUMENT_SEARCH_TOOL = {
    "name": "search_documents",
    "description": """Search the user's uploaded documents/workspace for relevant information.

ALWAYS use this tool when the user says any of:
- "search my documents", "search docs", "search workspace", "in my files"
- "what do my documents say about", "find in my uploads"
- "check my files", "look in my documents"

Also use for questions that might be answered by their uploaded documents.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query to find relevant document content. Be specific and use keywords."
            }
        },
        "required": ["query"]
    }
}

WEB_SEARCH_TOOL = {
    "name": "search_web",
    "description": """Search the internet for current information.

ALWAYS use this tool when the user says any of:
- "search the web", "search online", "search the internet", "google"
- "look up online", "find on the web", "what does the internet say"

Also use for questions about recent events, general knowledge not in documents, or when document search didn't find relevant results.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "The search query. Be specific and use keywords."
            }
        },
        "required": ["query"]
    }
}

BASE_SYSTEM_PROMPT = """You are a helpful assistant.

Be extremely concise. Respond like a human would in a chat - short, direct, no fluff.

Rules:
- Keep responses brief. One short sentence is often enough.
- For vague requests, ask ONE simple clarifying question. Don't list multiple questions or explain yourself.
- Never explain what you can or can't do. Just respond naturally.
- No bullet points or numbered lists for simple clarifications.
- When citing web sources, include markdown links like [source name](url).

Bad: "I'd be happy to help! However, I need more information. Could you tell me: 1) What you're building? 2) Do you have specs?"
Good: "What are you trying to build?"

Bad: "I don't have enough context to help with that. Could you provide more details about what you're looking for?"
Good: "Can you give me more details?"

Be human. Be brief."""


@dataclass
class ResourceInfo:
    """Information about a resource in the workspace."""
    name: str
    type: str  # "document" or "website"
    status: str  # "ready", "pending", "indexing", "failed"


def build_system_prompt(has_documents: bool, has_web_search: bool, resources: list[ResourceInfo] = None) -> str:
    """Build system prompt based on available tools and resources."""
    prompt_parts = [BASE_SYSTEM_PROMPT]

    # Add tools section
    tools_desc = []
    if has_documents:
        tools_desc.append("search_documents (search user's uploaded documents)")
    if has_web_search:
        tools_desc.append("search_web (search the internet)")

    if tools_desc:
        prompt_parts.append(f"Available tools: {', '.join(tools_desc)}.")

    # Add workspace resources section for self-awareness
    if resources:
        ready_resources = [r for r in resources if r.status == "ready"]
        pending_resources = [r for r in resources if r.status in ("pending", "indexing")]

        if ready_resources or pending_resources:
            resource_section = "\n\nWorkspace Resources (what you have access to):"

            if ready_resources:
                resource_section += "\n- Ready for search:"
                for r in ready_resources:
                    resource_section += f"\n  - {r.name} ({r.type})"

            if pending_resources:
                resource_section += "\n- Still processing:"
                for r in pending_resources:
                    resource_section += f"\n  - {r.name} ({r.type})"

            prompt_parts.append(resource_section)
    elif has_documents is False:
        prompt_parts.append("\n\nWorkspace Resources: None yet. The user hasn't uploaded any documents.")

    return "\n".join(prompt_parts)


def build_tools(has_documents: bool, has_web_search: bool) -> list:
    """Build tool list based on availability."""
    tools = []
    if has_documents:
        tools.append(DOCUMENT_SEARCH_TOOL)
    if has_web_search:
        tools.append(WEB_SEARCH_TOOL)
    return tools


@dataclass
class AgentEvent:
    """Event emitted by the agent during processing."""
    type: str  # "status", "tool_call", "tool_result", "chunk", "thinking"
    data: dict


class Agent:
    """Conversational agent with document search capability."""

    def __init__(
        self,
        retriever: Retriever,
        api_key: str = None,
        model: str = "claude-sonnet-4-20250514",
        max_tokens: int = 16000,  # Increased for extended thinking
        tavily_api_key: str = None,
        thinking_budget: int = 4096  # Budget for extended thinking tokens
    ):
        self.retriever = retriever
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.tavily_api_key = tavily_api_key or os.getenv("TAVILY_API_KEY")

    def _search_web(self, query: str) -> str:
        """Search the web using Tavily API."""
        if not self.tavily_api_key:
            return "Web search is not configured."

        try:
            response = requests.post(
                "https://api.tavily.com/search",
                json={
                    "api_key": self.tavily_api_key,
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
                return "No results found."

            parts = []
            for i, r in enumerate(results[:5], 1):
                title = r.get("title", "Untitled")
                content = r.get("content", "")[:500]
                url = r.get("url", "")
                parts.append(f"[{i}] [{title}]({url})\n{content}")

            return "\n\n---\n\n".join(parts) + "\n\nWhen citing these results, use markdown links like [text](url)."
        except Exception as e:
            return f"Web search failed: {str(e)}"

    def _format_search_results(self, results: list[RetrievalResult]) -> str:
        """Format search results for the agent."""
        if not results:
            return "No relevant documents found."

        parts = []
        for i, r in enumerate(results, 1):
            parts.append(f"[{i}] From {r.source}:\n{r.content}")
        return "\n\n---\n\n".join(parts)

    def _extract_snippet(self, content: str, max_length: int = 100) -> str:
        """Extract a meaningful snippet from content.

        Tries to find the first complete sentence, otherwise truncates at word boundary.
        """
        if not content:
            return ""

        content = content.strip()

        # If content is short enough, return as-is
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

    def chat(
        self,
        message: str,
        conversation_history: list[dict] = None,
        namespace: str = "",
        top_k: int = 5,
        has_documents: bool = True,
        resources: list[ResourceInfo] = None
    ) -> AgentResponse:
        """Have a conversation turn with the agent."""
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": message})

        all_sources = []
        used_search = False

        # Build tools and prompt based on what's available
        has_web_search = bool(self.tavily_api_key)
        tools = build_tools(has_documents, has_web_search)
        system_prompt = build_system_prompt(has_documents, has_web_search, resources)

        # Agentic loop - let Claude decide what to do
        while True:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=system_prompt,
                tools=tools if tools else None,
                messages=messages
            )

            # Check if Claude wants to use a tool
            if response.stop_reason == "tool_use":
                # Process tool calls
                tool_results = []
                for block in response.content:
                    if block.type == "tool_use":
                        if block.name == "search_documents":
                            used_search = True
                            query = block.input.get("query", message)
                            results = self.retriever.retrieve(
                                query=query,
                                top_k=top_k,
                                namespace=namespace
                            )
                            all_sources.extend(results)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": self._format_search_results(results)
                            })
                        elif block.name == "search_web":
                            query = block.input.get("query", message)
                            web_results = self._search_web(query)
                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": web_results
                            })

                # Add assistant's response and tool results to messages
                messages.append({"role": "assistant", "content": response.content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # Claude is done, extract the text response
                text_content = ""
                for block in response.content:
                    if hasattr(block, "text"):
                        text_content += block.text

                return AgentResponse(
                    content=text_content,
                    sources=all_sources,
                    used_search=used_search
                )

    def chat_stream_events(
        self,
        message: str,
        conversation_history: list[dict] = None,
        namespace: str = "",
        top_k: int = 5,
        has_documents: bool = True,
        resources: list[ResourceInfo] = None,
        enable_thinking: bool = True
    ) -> Iterator[AgentEvent]:
        """Stream a conversation turn with events for UI updates.

        Supports extended thinking which streams the agent's reasoning process.
        """
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": message})

        all_sources = []

        # Build tools and prompt based on what's available
        has_web_search = bool(self.tavily_api_key)
        tools = build_tools(has_documents, has_web_search)
        system_prompt = build_system_prompt(has_documents, has_web_search, resources)

        # Build thinking config if enabled
        thinking_config = None
        if enable_thinking and self.thinking_budget > 0:
            thinking_config = {
                "type": "enabled",
                "budget_tokens": self.thinking_budget
            }

        # Agentic loop
        while True:
            # Signal thinking status
            yield AgentEvent("status", {"status": "thinking"})

            # Use streaming with extended thinking to capture reasoning
            # We need to handle the stream to capture thinking blocks
            thinking_content = ""
            response_content = []
            stop_reason = None

            # Build API call kwargs
            api_kwargs = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "system": system_prompt,
                "messages": messages,
            }
            if tools:
                api_kwargs["tools"] = tools
            if thinking_config:
                api_kwargs["thinking"] = thinking_config

            # Use interleaved thinking beta header for tool use with thinking
            extra_headers = {}
            if thinking_config and tools:
                extra_headers["anthropic-beta"] = INTERLEAVED_THINKING_BETA

            with self.client.messages.stream(
                **api_kwargs,
                extra_headers=extra_headers if extra_headers else None
            ) as stream:
                current_block_type = None

                for event in stream:
                    if event.type == "content_block_start":
                        current_block_type = event.content_block.type
                        if current_block_type == "thinking":
                            # Start of thinking block
                            pass
                        elif current_block_type == "text":
                            # Start of text block
                            pass
                        elif current_block_type == "tool_use":
                            # Capture tool use block
                            response_content.append(event.content_block)

                    elif event.type == "content_block_delta":
                        if hasattr(event.delta, "thinking"):
                            # Stream thinking content
                            thinking_content += event.delta.thinking
                            yield AgentEvent("thinking", {"content": event.delta.thinking})
                        elif hasattr(event.delta, "text"):
                            # Stream text content (but we might need to handle tool use first)
                            yield AgentEvent("chunk", {"content": event.delta.text})
                        elif hasattr(event.delta, "partial_json"):
                            # Tool use input being streamed
                            pass

                    elif event.type == "content_block_stop":
                        current_block_type = None

                    elif event.type == "message_delta":
                        stop_reason = event.delta.stop_reason

                # Get the final message for tool use handling
                final_response = stream.get_final_message()
                response_content = final_response.content

            if stop_reason == "tool_use":
                # Process tool calls
                tool_results = []
                thinking_blocks = []

                for block in response_content:
                    # Preserve thinking blocks for the conversation
                    if block.type == "thinking":
                        thinking_blocks.append(block)
                    elif block.type == "tool_use":
                        if block.name == "search_documents":
                            query = block.input.get("query", message)

                            # Emit tool call event
                            yield AgentEvent("tool_call", {
                                "tool": "search_documents",
                                "query": query
                            })

                            results = self.retriever.retrieve(
                                query=query,
                                top_k=top_k,
                                namespace=namespace
                            )
                            all_sources.extend(results)

                            # Emit tool result event
                            yield AgentEvent("tool_result", {
                                "tool": "search_documents",
                                "found": len(results)
                            })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": self._format_search_results(results)
                            })

                        elif block.name == "search_web":
                            query = block.input.get("query", message)

                            # Emit tool call event
                            yield AgentEvent("tool_call", {
                                "tool": "search_web",
                                "query": query
                            })

                            web_results = self._search_web(query)
                            # Count results (rough estimate based on separators)
                            result_count = web_results.count("---") + 1 if "---" in web_results else (0 if "No results" in web_results or "failed" in web_results else 1)

                            # Emit tool result event
                            yield AgentEvent("tool_result", {
                                "tool": "search_web",
                                "found": result_count
                            })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": web_results
                            })

                # Emit sources (only for document search)
                if all_sources:
                    yield AgentEvent("sources", {
                        "sources": [
                            {
                                "content": r.content[:200] + "..." if len(r.content) > 200 else r.content,
                                "source": r.source,
                                "score": r.score,
                                "page_ref": r.metadata.get("page_ref"),
                                "page_numbers": r.metadata.get("page_numbers"),
                                "snippet": self._extract_snippet(r.content, 100),
                                "resource_id": r.metadata.get("resource_id")
                            }
                            for r in all_sources
                        ]
                    })

                # Add to messages and continue loop
                # Must preserve thinking blocks when passing back for tool results
                messages.append({"role": "assistant", "content": response_content})
                messages.append({"role": "user", "content": tool_results})
            else:
                # No tool use - we've already streamed the response
                # Send empty sources if no search was done
                if not all_sources:
                    yield AgentEvent("sources", {"sources": []})

                # Signal responding status (already streamed above)
                yield AgentEvent("status", {"status": "responding"})

                yield AgentEvent("done", {})
                return

    def chat_stream(
        self,
        message: str,
        conversation_history: list[dict] = None,
        namespace: str = "",
        top_k: int = 5,
        on_sources: Callable[[list[RetrievalResult]], None] = None,
        on_status: Callable[[str], None] = None
    ) -> Iterator[str]:
        """Stream a conversation turn with the agent (legacy interface)."""
        for event in self.chat_stream_events(message, conversation_history, namespace, top_k):
            if event.type == "status" and on_status:
                on_status(event.data["status"])
            elif event.type == "sources" and on_sources:
                # Convert back to RetrievalResult for compatibility
                results = [
                    RetrievalResult(
                        content=s["content"],
                        source=s["source"],
                        score=s["score"],
                        metadata={}
                    )
                    for s in event.data["sources"]
                ]
                on_sources(results)
            elif event.type == "chunk":
                yield event.data["content"]
