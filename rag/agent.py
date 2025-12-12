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
    """Plan for how to handle a user request (V1)."""
    category: str  # "chat", "doc_search", "web_search", "research", "analysis"
    acknowledgment: str  # What to tell the user we're doing
    thinking_budget: int  # Token budget for thinking (0 = disabled)
    search_strategy: str  # "none", "docs", "web", "both"
    complexity: str  # "simple", "moderate", "complex"
    needs_tools: bool  # Whether this request needs tool use


@dataclass
class RequestPlanV2(RequestPlan):
    """Enhanced plan for V2 agent with better intent understanding.

    New categories: "social", "factual", "clarification", "conversation"
    (in addition to existing: "chat", "doc_search", "web_search", "research", "analysis")
    """
    # Resource matching
    matched_resource: str | None = None  # Specific resource name if query maps to one
    matched_resource_id: str | None = None  # Resource ID for targeted search
    resource_confidence: float = 0.0  # 0.0-1.0 confidence in match

    # Direct responses (for social/clarification categories)
    direct_response: str | None = None  # The actual response for instant categories

    # Conversation context
    is_followup: bool = False  # True if this references prior conversation


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

SAVE_FINDING_TOOL = {
    "name": "save_finding",
    "description": """Save a key finding or insight to the user's workspace.

Use this tool when the user asks you to:
- "save this", "write this up", "add to my findings", "save to workspace"
- "remember this", "note this down", "add this as a finding"
- "write that up and save it", "save a summary"

The finding should be a clear, concise summary of the key insight or information.
Include enough context that it makes sense on its own.""",
    "input_schema": {
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
    system_instructions: str = None,
    context_only: bool = False
) -> str:
    """Build system prompt based on available tools, resources, and user instructions."""
    prompt_parts = [BASE_SYSTEM_PROMPT]

    # Add context-only mode instructions (highest priority constraint)
    if context_only:
        prompt_parts.append("""
## CONTEXT-ONLY MODE (STRICT)
You are in CONTEXT-ONLY mode. This means:
1. ONLY answer questions using information found in the user's uploaded documents
2. DO NOT use any knowledge from your training data
3. If the documents don't contain the answer, say "I couldn't find information about that in your documents"
4. ALWAYS search the documents before answering
5. Never make up or infer information not explicitly in the documents
6. Be explicit about which document the information came from""")

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


def build_tools(has_documents: bool, has_web_search: bool, can_save_findings: bool = False) -> list:
    """Build tool list based on availability."""
    tools = []
    if has_documents:
        tools.append(DOCUMENT_SEARCH_TOOL)
    if has_web_search:
        tools.append(WEB_SEARCH_TOOL)
    if can_save_findings:
        tools.append(SAVE_FINDING_TOOL)
    return tools


# Default agent version (can be overridden via env var or parameter)
AGENT_VERSION = os.getenv("AGENT_VERSION", "v2")  # "v1" or "v2"


# Router prompt for planning requests (V1 - original)
ROUTER_SYSTEM_PROMPT_V1 = """You are a request router. Analyze the user's message and decide how to handle it.

You must respond with a JSON object (no other text) with these fields:
- category: one of "chat", "doc_search", "web_search", "research", "analysis"
- acknowledgment: A brief, natural sentence describing what you're about to do. MUST reference the specific topic from the user's message. Keep it under 15 words.
- complexity: one of "simple", "moderate", "complex"
- search_strategy: one of "none", "docs", "web", "both"

Categories explained:
- "chat": Simple conversation, greetings, acknowledgments, clarifying questions
- "doc_search": User wants info from their uploaded documents
- "web_search": User wants current info from the web
- "research": User wants thorough research (may need multiple searches)
- "analysis": User wants deep analysis or comparison of information

CRITICAL - Acknowledgment rules:
1. ALWAYS include the specific topic/subject from the user's question
2. NEVER use generic phrases like "Let me help you with that" or "I'll look into that"
3. Reference what they're actually asking about

Examples of GOOD acknowledgments (specific to the question):
- User: "Can you find any invoices for Chris Polashenski?" → "Searching for invoices addressed to Chris Polashenski..."
- User: "What's the pinout for the sensor?" → "Looking up the sensor pinout information..."
- User: "Tell me about the authentication flow" → "Searching for authentication flow details..."
- User: "Find the pricing info" → "Searching for pricing information..."

Examples of BAD acknowledgments (too generic):
- "Let me help you with that." ❌
- "I'll search for that." ❌
- "Looking into it..." ❌

For document searches:
- If a filename/summary clearly matches the topic, be confident: "Searching your product datasheet for pinout info..."
- If no obvious match, still be specific about the topic: "Searching your workspace for Feather M0 information..."

For simple chat (greetings, thanks, etc.), use acknowledgment: "" (empty string).

Workspace resources (filenames are clues about content):
{resources}

Has documents: {has_documents}
Has web search: {has_web_search}"""


def build_router_prompt_v1(
    has_documents: bool,
    has_web_search: bool,
    resources: list[ResourceInfo] = None
) -> str:
    """Build the V1 router system prompt with context."""
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

    return ROUTER_SYSTEM_PROMPT_V1.format(
        resources=resource_text,
        has_documents=has_documents,
        has_web_search=has_web_search
    )


# ============================================================================
# V2 Router System Prompt (Context-Aware)
# ============================================================================

ROUTER_SYSTEM_PROMPT_V2 = """You are a request router. Analyze the user's message and context to decide how to handle it.

You must respond with a JSON object (no other text) with these fields:
- category: one of "social", "factual", "clarification", "doc_search", "web_search", "research", "analysis", "conversation"
- acknowledgment: Brief sentence describing what you're about to do (empty for social/factual/clarification)
- complexity: one of "instant", "simple", "moderate", "complex"
- search_strategy: one of "none", "docs", "web", "both"
- matched_resource: resource name if query clearly targets one specific resource, else null
- resource_confidence: 0.0-1.0 confidence in resource match
- direct_response: for social/clarification only - the actual response text
- is_followup: true if this references prior conversation

CATEGORIES explained:

1. "social" (instant, no tools) - Greetings, thanks, farewells
   - "hi", "thanks", "bye" → direct_response: "Hi! How can I help you today?"
   - ALWAYS set direct_response for social

2. "factual" (simple, no tools) - Simple facts the model knows
   - "what's 2+2?", "who wrote Hamlet?" → NO direct_response (Sonnet answers)
   - Only for facts that don't need document search

3. "clarification" (instant, no tools) - Ambiguous requests needing more info
   - Use when: no resources AND no conversation history AND vague query
   - "find pricing" with no context → direct_response: "What pricing are you looking for?"
   - "help" → direct_response: "What would you like help with?"
   - ALWAYS set direct_response for clarification

4. "doc_search" - User wants info from their documents
   - Use when: has_documents AND query is about something that might be in their files
   - ALWAYS set specific acknowledgment referencing the topic

5. "web_search" - User wants current info from the web
   - Use when: no relevant documents OR asking for current/latest info

6. "research" - Thorough research (multiple searches)
7. "analysis" - Deep analysis or comparison

8. "conversation" - Follow-up to prior conversation
   - Use when: is_followup=true and referencing prior context
   - "what else?", "tell me more", "expand on that"

CONTEXT-AWARE DECISION MATRIX:
| has_documents | has_history | query_type | → decision |
|---------------|-------------|------------|------------|
| true  | any   | mentions specific resource | doc_search (with matched_resource) |
| true  | any   | topical question | doc_search (generic) |
| false | true  | follow-up | conversation |
| false | false | vague | clarification |
| false | false | specific topic | web_search |
| any   | any   | greeting/thanks | social |

ACKNOWLEDGMENT RULES (for doc_search/web_search/research/analysis):

1. MATCH THE USER'S FRAMING - Don't always say "searching":
   - "help me calculate buoyancy" → "Sure, I'll help you calculate buoyancy."
   - "how do I wire the sensor?" → "I'll help you figure out the sensor wiring."
   - "search my docs for pricing" → "Searching your documents for pricing info..."
   - "find the pinout" → "Looking up the pinout information..."
   - "what's the voltage range?" → "Let me find the voltage range specs."

2. MATCH THE USER'S TONE - Mirror their energy and formality:
   - Frustrated/terse: "voltage specs" → "Looking up voltage specs." (brief, no fluff)
   - Casual: "hey can you find the pricing?" → "Sure, I'll look for the pricing info."
   - Enthusiastic: "omg please help me find this!!" → "On it! Let me dig through your docs."
   - Professional: "Please locate the authentication documentation" → "I'll search for the authentication documentation."

3. BE SPECIFIC - Always include the actual topic:
   - Include the specific subject from their question
   - If matched_resource is set, mention the resource name

GOOD acknowledgments:
- "Sure, I'll help you calculate buoyancy." ✓ (help request → help response)
- "Looking up the SAMD11 pinout..." ✓ (specific resource + topic)
- "On it! Searching for pricing info." ✓ (matches enthusiastic tone)
- "Checking voltage specifications." ✓ (matches terse tone)

BAD acknowledgments:
- "Let me help you with that." ❌ (too generic)
- "I'll look into that." ❌ (no topic)
- "Searching..." ❌ (no topic)
- "Searching your documents for buoyancy calculation..." ❌ (when user said "help me calculate", not "search for")

RESOURCE MATCHING:
- python_matched_resource: {python_matched_resource} (confidence: {python_match_confidence})
- If Python found a match, use it unless clearly wrong
- Otherwise, check if query topic clearly matches ONE resource name/summary
- If multiple could match, set matched_resource: null

CONTEXT:
- has_documents: {has_documents}
- has_web_search: {has_web_search}
- resource_count: {resource_count}
- has_conversation_history: {has_history}
- conversation_turn_count: {turn_count}
- python_matched_resource: {python_matched_resource}
- python_match_confidence: {python_match_confidence}

RESOURCES (names and summaries):
{resources}

Respond with JSON only."""


def build_router_prompt_v2(
    has_documents: bool,
    has_web_search: bool,
    resources: list[ResourceInfo] = None,
    has_history: bool = False,
    turn_count: int = 0,
    python_matched_resource: str = None,
    python_match_confidence: float = 0.0
) -> str:
    """Build the V2 router system prompt with enhanced context."""
    resource_text = "None"
    resource_count = 0

    if resources:
        ready = [r for r in resources if r.status == "ready"]
        resource_count = len(ready)
        if ready:
            resource_parts = []
            for r in ready:
                if r.summary:
                    resource_parts.append(f"- {r.name} ({r.type}): {r.summary}")
                else:
                    resource_parts.append(f"- {r.name} ({r.type})")
            resource_text = "\n".join(resource_parts)

    return ROUTER_SYSTEM_PROMPT_V2.format(
        resources=resource_text,
        has_documents=has_documents,
        has_web_search=has_web_search,
        resource_count=resource_count,
        has_history=has_history,
        turn_count=turn_count,
        python_matched_resource=python_matched_resource or "null",
        python_match_confidence=python_match_confidence
    )


# ============================================================================
# V2 Resource Matching Helpers
# ============================================================================

# Common stopwords to filter out from key terms
STOPWORDS = {
    "a", "an", "the", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "must", "shall", "can", "need", "dare",
    "ought", "used", "to", "of", "in", "for", "on", "with", "at", "by",
    "from", "as", "into", "through", "during", "before", "after", "above",
    "below", "between", "under", "again", "further", "then", "once", "here",
    "there", "when", "where", "why", "how", "all", "each", "few", "more",
    "most", "other", "some", "such", "no", "nor", "not", "only", "own",
    "same", "so", "than", "too", "very", "just", "and", "but", "if", "or",
    "because", "until", "while", "about", "against", "between", "into",
    "through", "during", "before", "after", "above", "below", "up", "down",
    "out", "off", "over", "under", "again", "further", "then", "once",
    "what", "which", "who", "whom", "this", "that", "these", "those",
    "am", "i", "me", "my", "myself", "we", "our", "ours", "ourselves",
    "you", "your", "yours", "yourself", "yourselves", "he", "him", "his",
    "himself", "she", "her", "hers", "herself", "it", "its", "itself",
    "they", "them", "their", "theirs", "themselves", "any", "both", "each",
    "find", "search", "look", "show", "tell", "get", "give", "help",
    "please", "thanks", "thank", "hi", "hello", "hey"
}


def extract_key_terms(text: str) -> set[str]:
    """Extract meaningful terms from text, filtering stopwords.

    Args:
        text: Input text (should be lowercased)

    Returns:
        Set of meaningful terms (lowercased, no stopwords)
    """
    # Split on non-alphanumeric characters
    terms = re.split(r'[^a-z0-9]+', text.lower())
    # Filter out stopwords and short terms
    return {term for term in terms if term and len(term) > 2 and term not in STOPWORDS}


def match_query_to_resource(
    query: str,
    resources: list[ResourceInfo]
) -> tuple[str | None, str | None, float]:
    """Match query to specific resource using Python heuristics.

    Strategy:
    1. Exact name match (0.9 confidence) - "SAMD11" in query + "SAMD11-datasheet.pdf"
    2. Keyword overlap with filename (0.7) - "sensor" in query + "SensorManual.pdf"
    3. No match (0.0) - let router LLM decide based on summaries

    Args:
        query: User's query text
        resources: List of available resources

    Returns:
        (resource_name, resource_id, confidence) tuple
    """
    query_lower = query.lower()
    query_terms = extract_key_terms(query_lower)

    best_match = (None, None, 0.0)

    for resource in resources:
        if resource.status != "ready":
            continue

        name_lower = resource.name.lower()
        # Remove common extensions for matching
        name_base = re.sub(r'\.(pdf|txt|md|doc|docx|csv|xlsx|json|html|py|js|ts|tsx|jsx)$', '', name_lower)
        # Also remove common suffixes like -datasheet, _manual, etc
        name_base = re.sub(r'[-_](datasheet|manual|guide|spec|docs?|readme)$', '', name_base)

        # Check 1: Exact name base mention in query (high confidence)
        # Split name_base into parts (handles dashes, underscores)
        name_parts = re.split(r'[-_\s]+', name_base)
        for part in name_parts:
            if len(part) >= 3 and part in query_lower:
                # Found exact mention of a significant part of the filename
                return (resource.name, resource.id, 0.9)

        # Check 2: Keyword overlap with filename (medium confidence)
        name_terms = extract_key_terms(name_base)
        overlap = query_terms & name_terms
        if overlap:
            overlap_score = len(overlap) / max(len(query_terms), 1)
            confidence = min(0.7, 0.4 + overlap_score * 0.3)
            if confidence > best_match[2]:
                best_match = (resource.name, resource.id, confidence)

    return best_match


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
        thinking_budget: int = 4096,  # Budget for extended thinking tokens
        version: str = None  # Agent version: "v1" or "v2"
    ):
        self.retriever = retriever
        self.model = model
        self.max_tokens = max_tokens
        self.thinking_budget = thinking_budget
        self.client = Anthropic(api_key=api_key or os.getenv("ANTHROPIC_API_KEY"))
        self.tavily_api_key = tavily_api_key or os.getenv("TAVILY_API_KEY")
        self.version = version or AGENT_VERSION

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

    def _plan_request_v1(
        self,
        message: str,
        has_documents: bool = True,
        has_web_search: bool = False,
        resources: list[ResourceInfo] = None,
        router_model: str = "claude-3-haiku-20240307"
    ) -> RequestPlan:
        """V1: Use a fast model to plan how to handle the request.

        Returns a RequestPlan with categorization, acknowledgment, and strategy.
        """
        router_prompt = build_router_prompt_v1(has_documents, has_web_search, resources)

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
            # Generate a contextual fallback acknowledgment
            msg_lower = message.lower()
            # Extract a simple topic-based acknowledgment
            if "invoice" in msg_lower:
                fallback_ack = "Searching for invoice information..."
            elif "find" in msg_lower or "search" in msg_lower:
                fallback_ack = f"Searching your documents..."
            elif "what" in msg_lower or "how" in msg_lower or "?" in message:
                fallback_ack = "Looking that up..."
            else:
                fallback_ack = "Searching your workspace..."
            return RequestPlan(
                category="chat",
                acknowledgment=fallback_ack,
                thinking_budget=self.thinking_budget,
                search_strategy="docs" if has_documents else "none",
                complexity="moderate",
                needs_tools=has_documents
            )

    def _plan_request_v2(
        self,
        message: str,
        has_documents: bool = True,
        has_web_search: bool = False,
        resources: list[ResourceInfo] = None,
        conversation_history: list[dict] = None,
        router_model: str = "claude-3-haiku-20240307"
    ) -> RequestPlanV2:
        """V2: Enhanced request planning with context-awareness.

        Features:
        - Python-based resource matching before LLM call
        - Conversation history awareness
        - New categories: social, factual, clarification
        - Direct response generation for instant categories

        Returns RequestPlanV2 with enhanced fields.
        """
        # Determine conversation context
        has_history = bool(conversation_history and len(conversation_history) > 0)
        turn_count = len(conversation_history) // 2 if conversation_history else 0

        # Python-first resource matching
        python_matched_resource = None
        python_matched_id = None
        python_match_confidence = 0.0

        if resources:
            python_matched_resource, python_matched_id, python_match_confidence = \
                match_query_to_resource(message, resources)

        # Build V2 router prompt with all context
        router_prompt = build_router_prompt_v2(
            has_documents=has_documents,
            has_web_search=has_web_search,
            resources=resources,
            has_history=has_history,
            turn_count=turn_count,
            python_matched_resource=python_matched_resource,
            python_match_confidence=python_match_confidence
        )

        try:
            response = self.client.messages.create(
                model=router_model,
                max_tokens=512,  # Larger for direct_response field
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

            # Extract category and complexity
            category = plan_data.get("category", "doc_search")
            complexity = plan_data.get("complexity", "moderate")

            # Determine thinking budget based on complexity
            if complexity == "instant":
                thinking_budget = 0
            elif complexity == "simple":
                thinking_budget = 0
            elif complexity == "complex":
                thinking_budget = self.thinking_budget * 2
            else:
                thinking_budget = self.thinking_budget

            # Determine if tools are needed
            search_strategy = plan_data.get("search_strategy", "none")
            needs_tools = search_strategy != "none"

            # Extract V2-specific fields
            matched_resource = plan_data.get("matched_resource")
            resource_confidence = plan_data.get("resource_confidence", 0.0)
            direct_response = plan_data.get("direct_response")
            is_followup = plan_data.get("is_followup", False)

            # Use Python-matched resource if LLM didn't find one and we have high confidence
            if not matched_resource and python_matched_resource and python_match_confidence >= 0.7:
                matched_resource = python_matched_resource
                resource_confidence = python_match_confidence

            # Get matched resource ID
            matched_resource_id = None
            if matched_resource and resources:
                for r in resources:
                    if r.name == matched_resource:
                        matched_resource_id = r.id
                        break
            # Fall back to Python-matched ID
            if not matched_resource_id and python_matched_id:
                matched_resource_id = python_matched_id

            return RequestPlanV2(
                category=category,
                acknowledgment=plan_data.get("acknowledgment", ""),
                thinking_budget=thinking_budget,
                search_strategy=search_strategy,
                complexity=complexity,
                needs_tools=needs_tools,
                matched_resource=matched_resource,
                matched_resource_id=matched_resource_id,
                resource_confidence=resource_confidence,
                direct_response=direct_response,
                is_followup=is_followup
            )

        except Exception as e:
            # Fallback plan if API call or parsing fails
            print(f"[Router V2] Error: {e}")

            # Generate a contextual fallback acknowledgment
            msg_lower = message.lower()

            # Check for social patterns first
            social_patterns = ["^hi$", "^hello$", "^hey$", "^thanks", "^thank you", "^bye$", "^goodbye$"]
            for pattern in social_patterns:
                if re.match(pattern, msg_lower.strip()):
                    return RequestPlanV2(
                        category="social",
                        acknowledgment="",
                        thinking_budget=0,
                        search_strategy="none",
                        complexity="instant",
                        needs_tools=False,
                        direct_response="Hi! How can I help you today?" if "hi" in msg_lower or "hello" in msg_lower or "hey" in msg_lower else "You're welcome!",
                        is_followup=False
                    )

            # Fallback to doc_search with contextual acknowledgment
            if "invoice" in msg_lower:
                fallback_ack = "Searching for invoice information..."
            elif "find" in msg_lower or "search" in msg_lower:
                fallback_ack = "Searching your documents..."
            elif "what" in msg_lower or "how" in msg_lower or "?" in message:
                fallback_ack = "Looking that up..."
            else:
                fallback_ack = "Searching your workspace..."

            return RequestPlanV2(
                category="doc_search" if has_documents else "chat",
                acknowledgment=fallback_ack,
                thinking_budget=self.thinking_budget,
                search_strategy="docs" if has_documents else "none",
                complexity="moderate",
                needs_tools=has_documents,
                matched_resource=python_matched_resource,
                matched_resource_id=python_matched_id,
                resource_confidence=python_match_confidence,
                direct_response=None,
                is_followup=has_history
            )

    def plan_request(
        self,
        message: str,
        has_documents: bool = True,
        has_web_search: bool = False,
        resources: list[ResourceInfo] = None,
        conversation_history: list[dict] = None,
        router_model: str = "claude-3-haiku-20240307"
    ) -> RequestPlan | RequestPlanV2:
        """Route to V1 or V2 based on agent version.

        Returns RequestPlan (V1) or RequestPlanV2 (V2) based on self.version.
        """
        if self.version == "v2":
            return self._plan_request_v2(
                message=message,
                has_documents=has_documents,
                has_web_search=has_web_search,
                resources=resources,
                conversation_history=conversation_history,
                router_model=router_model
            )
        else:
            return self._plan_request_v1(
                message=message,
                has_documents=has_documents,
                has_web_search=has_web_search,
                resources=resources,
                router_model=router_model
            )

    def chat(
        self,
        message: str,
        conversation_history: list[dict] = None,
        namespace: str = "",
        namespaces: list[str] = None,
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
                                namespace=namespace,
                                namespaces=namespaces
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
        namespaces: list[str] = None,
        top_k: int = 5,
        has_documents: bool = True,
        resources: list[ResourceInfo] = None,
        enable_thinking: bool = True,
        system_instructions: str = None,
        context_only: bool = False,
        save_finding_callback: Callable[[str, str | None], dict] = None
    ) -> Iterator[AgentEvent]:
        """Stream a conversation turn with events for UI updates.

        Supports extended thinking which streams the agent's reasoning process.
        When context_only=True, only uses document search (no web, no training data).

        Args:
            save_finding_callback: Optional callback to save findings. Takes (content, note) and returns finding dict.
        """
        messages = list(conversation_history or [])
        messages.append({"role": "user", "content": message})

        all_sources = []

        # Build tools and prompt based on what's available
        # In context_only mode, disable web search
        has_web_search = bool(self.tavily_api_key) and not context_only
        can_save_findings = save_finding_callback is not None
        tools = build_tools(has_documents, has_web_search, can_save_findings)
        system_prompt = build_system_prompt(has_documents, has_web_search, resources, system_instructions, context_only)

        # Step 1: Plan the request using the router
        plan = self.plan_request(
            message=message,
            has_documents=has_documents,
            has_web_search=has_web_search,
            resources=resources,
            conversation_history=conversation_history
        )
        print(f"[Router] Plan: category={plan.category}, acknowledgment='{plan.acknowledgment}', complexity={plan.complexity}")

        # Emit the plan event with acknowledgment (include V2 fields if available)
        plan_event_data = {
            "category": plan.category,
            "acknowledgment": plan.acknowledgment,
            "complexity": plan.complexity,
            "search_strategy": plan.search_strategy
        }
        # Add V2 fields if present
        if isinstance(plan, RequestPlanV2):
            plan_event_data["matched_resource"] = plan.matched_resource
            plan_event_data["resource_confidence"] = plan.resource_confidence
            plan_event_data["is_followup"] = plan.is_followup

        yield AgentEvent("plan", plan_event_data)

        # =====================================================================
        # V2 FAST PATHS: Handle instant responses without full agentic loop
        # =====================================================================
        if self.version == "v2" and isinstance(plan, RequestPlanV2):

            # Fast path 1: SOCIAL (greetings, thanks) - Haiku already generated response
            # IMPORTANT: Only use social fast path if there's NO conversation history
            # "Awesome!", "thanks", etc. mid-conversation are acknowledgments, not greetings
            has_history = bool(conversation_history and len(conversation_history) > 0)
            if plan.category == "social" and plan.direct_response and not has_history:
                print(f"[V2 Fast Path] Social response: {plan.direct_response}")
                yield AgentEvent("chunk", {"content": plan.direct_response})
                yield AgentEvent("sources", {"sources": []})
                yield AgentEvent("usage", {"input_tokens": 0, "output_tokens": 0})
                yield AgentEvent("done", {})
                return
            elif plan.category == "social" and has_history:
                # Mid-conversation acknowledgment - let Sonnet handle naturally
                print(f"[V2] Social blocked - has conversation history, falling through to Sonnet")

            # Fast path 2: CLARIFICATION - Haiku already generated question
            # IMPORTANT: Only use clarification fast path if there's NO conversation history
            # If there IS history, the user is likely referencing prior context (e.g., "these", "that")
            if plan.category == "clarification" and plan.direct_response and not has_history:
                print(f"[V2 Fast Path] Clarification: {plan.direct_response}")
                yield AgentEvent("chunk", {"content": plan.direct_response})
                yield AgentEvent("sources", {"sources": []})
                yield AgentEvent("usage", {"input_tokens": 0, "output_tokens": 0})
                yield AgentEvent("done", {})
                return
            elif plan.category == "clarification" and has_history:
                # Router incorrectly classified as clarification despite history
                # Fall through to normal flow so Sonnet can use the context
                print(f"[V2] Clarification blocked - has conversation history, falling through to Sonnet")

            # Fast path 3: FACTUAL - Call Sonnet directly, no tools, no thinking
            if plan.category == "factual":
                print(f"[V2 Fast Path] Factual query - using Sonnet without tools/thinking")
                yield AgentEvent("status", {"status": "thinking"})

                try:
                    with self.client.messages.stream(
                        model=self.model,
                        max_tokens=self.max_tokens,
                        system="You are a helpful assistant. Answer the user's question directly and concisely.",
                        messages=messages
                    ) as stream:
                        for event in stream:
                            if event.type == "content_block_delta":
                                if hasattr(event.delta, "text"):
                                    yield AgentEvent("chunk", {"content": event.delta.text})

                        # Get final message for usage
                        final_message = stream.get_final_message()
                        yield AgentEvent("sources", {"sources": []})
                        yield AgentEvent("usage", {
                            "input_tokens": final_message.usage.input_tokens,
                            "output_tokens": final_message.usage.output_tokens
                        })
                        yield AgentEvent("done", {})
                        return

                except Exception as e:
                    print(f"[V2 Fast Path] Factual error: {e}, falling back to normal flow")
                    # Fall through to normal agentic loop

        # =====================================================================
        # Normal flow (V1, or V2 with doc_search/web_search/research/analysis)
        # =====================================================================

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
                                namespace=namespace,
                                namespaces=namespaces
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

                        elif block.name == "save_finding":
                            content = block.input.get("content", "")
                            note = block.input.get("note")

                            # Emit tool call event
                            yield AgentEvent("tool_call", {
                                "tool": "save_finding",
                                "content": content[:100] + "..." if len(content) > 100 else content
                            })

                            # Save the finding using the callback
                            if save_finding_callback:
                                try:
                                    finding = save_finding_callback(content, note)
                                    result_message = f"Finding saved successfully with ID: {finding.get('id', 'unknown')}"

                                    # Emit tool result event with saved flag for frontend
                                    yield AgentEvent("tool_result", {
                                        "tool": "save_finding",
                                        "found": 1,
                                        "query": content[:50] + "..." if len(content) > 50 else content,
                                        "saved": True,
                                        "finding_id": finding.get("id"),
                                        "finding_content": finding.get("content")
                                    })
                                except Exception as e:
                                    result_message = f"Failed to save finding: {str(e)}"
                                    yield AgentEvent("tool_result", {
                                        "tool": "save_finding",
                                        "found": 0,
                                        "error": str(e)
                                    })
                            else:
                                result_message = "Finding could not be saved: save_finding_callback not configured"
                                yield AgentEvent("tool_result", {
                                    "tool": "save_finding",
                                    "found": 0,
                                    "error": "Not configured"
                                })

                            tool_results.append({
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_message
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
