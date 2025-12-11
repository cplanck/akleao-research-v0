"""Agentic LLM module - conversational assistant with tool use."""

import json
import os
import re
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


@dataclass
class ThinkingConfig:
    """Configuration for extended thinking based on query complexity."""
    enabled: bool
    budget_tokens: int
    reason: str  # Why this config was chosen


@dataclass
class RequestPlan:
    """Plan for how to handle a user request."""
    category: str  # "chat", "doc_search", "web_search", "research", "analysis"
    acknowledgment: str  # What to tell the user we're doing
    thinking_budget: int  # Token budget for thinking (0 = disabled)
    search_strategy: str  # "none", "docs", "web", "both"
    complexity: str  # "simple", "moderate", "complex"
    needs_tools: bool  # Whether this request needs tool use


# Patterns for simple queries that don't need thinking
SIMPLE_QUERY_PATTERNS = [
    # Greetings
    r"^(hi|hello|hey|howdy|greetings|good morning|good afternoon|good evening)[\s!.?]*$",
    # Acknowledgments
    r"^(thanks|thank you|thx|ty|ok|okay|cool|great|perfect|awesome|nice|got it|understood|i see|makes sense)[\s!.?]*$",
    # Single word responses
    r"^(yes|no|yep|nope|sure|maybe|probably|absolutely|definitely|correct|right|wrong)[\s!.?]*$",
    # Farewells
    r"^(bye|goodbye|see ya|later|take care|cheers)[\s!.?]*$",
]

# Patterns for "think deeper" requests that need extended budget
DEEP_THINKING_PATTERNS = [
    r"think (harder|deeper|more|carefully|thoroughly|about it|on it|this through)",
    r"(really|carefully|thoroughly|deeply) (think|consider|analyze|examine)",
    r"take your time",
    r"(analyze|examine|consider|review) (this |it )?(carefully|thoroughly|deeply|in detail)",
    r"give (this |it )?(more|careful|thorough|deep) (thought|consideration|analysis)",
    r"(more|deeper|thorough|detailed|careful) analysis",
    r"think step by step",
    r"let's think",
    r"reason (through|about)",
]


def analyze_query_complexity(
    message: str,
    base_budget: int = 4096,
    deep_budget: int = 10000
) -> ThinkingConfig:
    """Analyze query complexity to determine thinking configuration.

    Returns:
        ThinkingConfig with:
        - Simple queries: thinking disabled (instant response)
        - Normal queries: standard thinking budget
        - Deep thinking requests: extended budget for thorough analysis
    """
    msg_lower = message.strip().lower()

    # Check for simple queries first (no thinking needed)
    for pattern in SIMPLE_QUERY_PATTERNS:
        if re.match(pattern, msg_lower, re.IGNORECASE):
            return ThinkingConfig(
                enabled=False,
                budget_tokens=0,
                reason="simple_query"
            )

    # Check for explicit "think deeper" requests (extended budget)
    for pattern in DEEP_THINKING_PATTERNS:
        if re.search(pattern, msg_lower, re.IGNORECASE):
            return ThinkingConfig(
                enabled=True,
                budget_tokens=deep_budget,
                reason="deep_thinking_requested"
            )

    # Default: normal thinking with standard budget
    return ThinkingConfig(
        enabled=True,
        budget_tokens=base_budget,
        reason="normal_query"
    )


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
    summary: str | None = None  # LLM-generated summary of the document content


def build_system_prompt(
    has_documents: bool,
    has_web_search: bool,
    resources: list[ResourceInfo] = None,
    system_instructions: str = None
) -> str:
    """Build system prompt based on available tools, resources, and user instructions."""
    prompt_parts = [BASE_SYSTEM_PROMPT]

    # Add user-defined workspace instructions (highest priority)
    if system_instructions and system_instructions.strip():
        prompt_parts.append(f"\n\n## User Instructions (IMPORTANT - follow these for this workspace)\n{system_instructions.strip()}")

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


# Router prompt for planning requests
ROUTER_SYSTEM_PROMPT = """You are a request router. Analyze the user's message and decide how to handle it.

You must respond with a JSON object (no other text) with these fields:
- category: one of "chat", "doc_search", "web_search", "research", "analysis"
- acknowledgment: A brief, natural sentence telling the user what you're about to do. Be conversational and specific. Reference their actual question/topic. Keep it under 15 words.
- complexity: one of "simple", "moderate", "complex"
- search_strategy: one of "none", "docs", "web", "both"

Categories explained:
- "chat": Simple conversation, greetings, acknowledgments, clarifying questions
- "doc_search": User wants info from their uploaded documents
- "web_search": User wants current info from the web
- "research": User wants thorough research (may need multiple searches)
- "analysis": User wants deep analysis or comparison of information

IMPORTANT for acknowledgments:
- Look at the resource filenames/summaries below to judge if the documents might contain what the user is asking about
- If a filename/summary clearly matches the topic (e.g., "XYZ_datasheet.pdf" for a question about XYZ), be confident: "Searching your XYZ datasheet..."
- If the query topic doesn't obviously match any filenames, use neutral language: "Searching your workspace for [topic] information..."
- Never imply the user has documents about a topic unless filenames/summaries suggest it

Acknowledgment examples:
- Confident (filename matches): "Searching your product datasheet for pinout info..."
- Neutral (no obvious match): "Searching your workspace for Feather M0 information..."
- Neutral: "Checking your workspace for authentication details..."
- Web search: "Let me check the web for the latest on that."

For simple chat (greetings, thanks, etc.), use acknowledgment: "" (empty string).

Workspace resources (filenames are clues about content):
{resources}

Has documents: {has_documents}
Has web search: {has_web_search}"""


def build_router_prompt(
    has_documents: bool,
    has_web_search: bool,
    resources: list[ResourceInfo] = None
) -> str:
    """Build the router system prompt with context."""
    resource_text = "None"
    if resources:
        ready = [r for r in resources if r.status == "ready"]
        if ready:
            # Build detailed resource list with summaries
            resource_parts = []
            for r in ready:
                if r.summary:
                    resource_parts.append(f"- {r.name} ({r.type}): {r.summary}")
                else:
                    resource_parts.append(f"- {r.name} ({r.type})")
            resource_text = "\n".join(resource_parts)

    return ROUTER_SYSTEM_PROMPT.format(
        resources=resource_text,
        has_documents=has_documents,
        has_web_search=has_web_search
    )


@dataclass
class AgentEvent:
    """Event emitted by the agent during processing."""
    type: str  # "plan", "status", "tool_call", "tool_result", "chunk", "thinking", "sources", "usage", "done"
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

    def _format_source_info(self, result: RetrievalResult) -> dict:
        """Format a retrieval result into a source info dict with GitHub URL if available."""
        metadata = result.metadata

        # Build base source info
        source_info = {
            "content": result.content[:200] + "..." if len(result.content) > 200 else result.content,
            "source": result.source,
            "score": result.score,
            "page_ref": metadata.get("page_ref"),
            "page_numbers": metadata.get("page_numbers"),
            "snippet": self._extract_snippet(result.content, 100),
            "resource_id": metadata.get("resource_id"),
            "line_start": metadata.get("line_start"),
            "line_end": metadata.get("line_end"),
            "github_url": None
        }

        # Build GitHub URL if we have the necessary metadata
        github_base_url = metadata.get("github_base_url")
        file_path = metadata.get("file_path")
        line_start = metadata.get("line_start")
        line_end = metadata.get("line_end")

        if github_base_url and file_path:
            # Construct URL: base/file_path#L{start}-L{end}
            github_url = f"{github_base_url}/{file_path}"
            if line_start and line_end:
                github_url += f"#L{line_start}-L{line_end}"
            elif line_start:
                github_url += f"#L{line_start}"
            source_info["github_url"] = github_url

        return source_info

    def plan_request(
        self,
        message: str,
        has_documents: bool = True,
        has_web_search: bool = False,
        resources: list[ResourceInfo] = None,
        router_model: str = "claude-3-haiku-20240307"
    ) -> RequestPlan:
        """Use a fast model to plan how to handle the request.

        Returns a RequestPlan with categorization, acknowledgment, and strategy.
        """
        router_prompt = build_router_prompt(has_documents, has_web_search, resources)

        try:
            response = self.client.messages.create(
                model=router_model,
                max_tokens=256,
                system=router_prompt,
                messages=[{"role": "user", "content": message}]
            )

            # Parse the JSON response
            response_text = response.content[0].text.strip()
            # Handle potential markdown code blocks
            if response_text.startswith("```"):
                response_text = response_text.split("```")[1]
                if response_text.startswith("json"):
                    response_text = response_text[4:]
                response_text = response_text.strip()

            plan_data = json.loads(response_text)

            # Determine thinking budget based on complexity
            complexity = plan_data.get("complexity", "moderate")
            if complexity == "simple":
                thinking_budget = 0
            elif complexity == "complex":
                thinking_budget = self.thinking_budget * 2
            else:
                thinking_budget = self.thinking_budget

            # Determine if tools are needed
            search_strategy = plan_data.get("search_strategy", "none")
            needs_tools = search_strategy != "none"

            return RequestPlan(
                category=plan_data.get("category", "chat"),
                acknowledgment=plan_data.get("acknowledgment", ""),
                thinking_budget=thinking_budget,
                search_strategy=search_strategy,
                complexity=complexity,
                needs_tools=needs_tools
            )

        except Exception as e:
            # Fallback plan if API call or parsing fails
            print(f"[Router] Error: {e}")
            return RequestPlan(
                category="chat",
                acknowledgment="Let me help you with that.",
                thinking_budget=self.thinking_budget,
                search_strategy="docs" if has_documents else "none",
                complexity="moderate",
                needs_tools=has_documents
            )

    def chat(
        self,
        message: str,
        conversation_history: list[dict] = None,
        namespace: str = "",
        top_k: int = 5,
        has_documents: bool = True,
        resources: list[ResourceInfo] = None,
        system_instructions: str = None
    ) -> AgentResponse:
        """Have a conversation turn with the agent."""
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": message})

        all_sources = []
        used_search = False

        # Build tools and prompt based on what's available
        has_web_search = bool(self.tavily_api_key)
        tools = build_tools(has_documents, has_web_search)
        system_prompt = build_system_prompt(has_documents, has_web_search, resources, system_instructions)

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
        enable_thinking: bool = True,
        system_instructions: str = None
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
        system_prompt = build_system_prompt(has_documents, has_web_search, resources, system_instructions)

        # Step 1: Plan the request using the router
        plan = self.plan_request(
            message=message,
            has_documents=has_documents,
            has_web_search=has_web_search,
            resources=resources
        )
        print(f"[Router] Plan: category={plan.category}, acknowledgment='{plan.acknowledgment}', complexity={plan.complexity}")

        # Emit the plan event with acknowledgment
        yield AgentEvent("plan", {
            "category": plan.category,
            "acknowledgment": plan.acknowledgment,
            "complexity": plan.complexity,
            "search_strategy": plan.search_strategy
        })

        # Build thinking config based on the plan's complexity
        thinking_config = None
        if enable_thinking and plan.thinking_budget > 0:
            thinking_config = {
                "type": "enabled",
                "budget_tokens": plan.thinking_budget
            }

        # Token usage tracking across the agentic loop
        total_input_tokens = 0
        total_output_tokens = 0

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

                # Accumulate token usage
                if hasattr(final_response, 'usage') and final_response.usage:
                    total_input_tokens += final_response.usage.input_tokens
                    total_output_tokens += final_response.usage.output_tokens

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
                                "found": len(results),
                                "query": query
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
                                "found": result_count,
                                "query": query
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
                            self._format_source_info(r)
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

                # Emit token usage
                yield AgentEvent("usage", {
                    "input_tokens": total_input_tokens,
                    "output_tokens": total_output_tokens,
                    "total_tokens": total_input_tokens + total_output_tokens
                })

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
