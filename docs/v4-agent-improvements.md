# V4 Agent Improvements Specification

This document outlines proposed improvements for the Akleao Research agent, building on V3's resource awareness and intent detection capabilities.

## Overview

V4 focuses on three pillars:
1. **Speed** - Faster response times through parallelization and caching
2. **Intelligence** - Smarter reasoning and cross-resource synthesis
3. **Intent Detection** - More nuanced understanding of user goals

---

## 1. Speed Improvements

### 1.1 Parallel Tool Execution

**Problem**: Tools currently execute sequentially in the agentic loop. When Claude calls multiple tools, each waits for the previous to complete.

**Solution**: Execute independent tools in parallel using `asyncio` or `concurrent.futures`.

**Implementation**:
```python
# In chat_stream_events, when processing tool calls:
import asyncio
from concurrent.futures import ThreadPoolExecutor

async def execute_tools_parallel(tool_blocks, resources, ...):
    """Execute independent tools in parallel."""
    with ThreadPoolExecutor(max_workers=4) as executor:
        loop = asyncio.get_event_loop()
        tasks = []
        for block in tool_blocks:
            if block.name == "search_documents":
                tasks.append(loop.run_in_executor(executor, search_docs, block))
            elif block.name == "list_resources":
                tasks.append(loop.run_in_executor(executor, list_resources, block))
            # ... etc
        results = await asyncio.gather(*tasks)
    return results
```

**Expected Impact**: 2-3x speedup when multiple tools are called (common in research queries).

---

### 1.2 Resource Info Caching

**Problem**: Every query rebuilds the full resource list from the database, even though resources rarely change mid-session.

**Solution**: Add a TTL cache for resource metadata.

**Implementation**:
```python
from functools import lru_cache
import time

class Agent:
    def __init__(self, ...):
        self._resource_cache = {}
        self._cache_ttl = 60  # seconds

    def _get_resources_cached(self, project_id: str) -> list[ResourceInfo]:
        """Get resources with 60-second cache."""
        cache_key = project_id
        now = time.time()

        if cache_key in self._resource_cache:
            cached, timestamp = self._resource_cache[cache_key]
            if now - timestamp < self._cache_ttl:
                return cached

        # Fetch fresh
        resources = self._fetch_resources(project_id)
        self._resource_cache[cache_key] = (resources, now)
        return resources

    def invalidate_cache(self, project_id: str):
        """Call when resources are added/removed."""
        self._resource_cache.pop(project_id, None)
```

**Expected Impact**: Eliminates DB round-trip for most queries in a session.

---

### 1.3 Regex Pre-Router (Instant Path)

**Problem**: Even simple queries ("hi", "thanks", "what files do I have?") go through the Haiku router, adding ~200-400ms latency.

**Solution**: Add a regex-based pre-router that catches obvious patterns before LLM routing.

**Implementation**:
```python
# Add to agent.py before plan_request

INSTANT_PATTERNS = {
    # Social - instant response, no tools
    "social": [
        (r"^(hi|hello|hey|howdy)[\s!.?]*$", "Hi! How can I help you today?"),
        (r"^(thanks|thank you|thx|ty)[\s!.?]*$", "You're welcome!"),
        (r"^(bye|goodbye|see ya)[\s!.?]*$", "Goodbye! Feel free to come back anytime."),
    ],
    # Resource queries - trigger list_resources directly
    "resource_query": [
        r"^what (files|documents|resources) do i have",
        r"^(show|list) (my |me )?(files|documents|resources|uploads)",
        r"^what('s| is) in my (workspace|project)",
    ],
    # Factual - skip tools entirely
    "factual": [
        r"^what('s| is) \d+\s*[\+\-\*\/]\s*\d+",  # math
        r"^(who|what|when|where) (is|was|are|were) [A-Z]",  # simple facts
    ],
}

def pre_route(message: str) -> RequestPlanV3 | None:
    """Instant routing for obvious patterns. Returns None if LLM routing needed."""
    msg_lower = message.lower().strip()

    for category, patterns in INSTANT_PATTERNS.items():
        for pattern in patterns:
            if isinstance(pattern, tuple):
                regex, response = pattern
                if re.match(regex, msg_lower, re.IGNORECASE):
                    return RequestPlanV3(
                        category=category,
                        direct_response=response,
                        complexity="instant",
                        thinking_budget=0,
                        needs_tools=False,
                        intent_mode="action",
                        response_style="conversational"
                    )
            else:
                if re.match(pattern, msg_lower, re.IGNORECASE):
                    return RequestPlanV3(
                        category=category,
                        complexity="simple",
                        needs_tools=(category == "resource_query"),
                        intent_mode="action",
                        response_style="structured"
                    )
    return None  # Fall through to LLM router
```

**Expected Impact**: ~300ms savings for 20-30% of queries.

---

### 1.4 Speculative Resource Prefetching

**Problem**: When the router identifies a `matched_resource`, we wait for Sonnet to think before loading the file.

**Solution**: Start loading the matched resource in a background thread while Sonnet processes.

**Implementation**:
```python
from concurrent.futures import ThreadPoolExecutor

# In chat_stream_events, after plan is generated:
prefetch_executor = ThreadPoolExecutor(max_workers=1)
prefetch_future = None

if plan.matched_resource:
    # Start loading resource in background
    prefetch_future = prefetch_executor.submit(
        self._prefetch_resource,
        plan.matched_resource,
        resources
    )

# Later, when tool needs the resource:
if prefetch_future:
    prefetched_data = prefetch_future.result(timeout=5)
```

---

## 2. Intelligence Improvements

### 2.1 Adaptive System Prompt

**Problem**: V3 detects `response_style` but doesn't use it to guide the response.

**Solution**: Inject style-specific instructions into the system prompt.

**Implementation**:
```python
STYLE_INSTRUCTIONS = {
    "conversational": """
## Response Style: Conversational
- Be warm and engaging
- Offer 2-3 follow-up directions the user might explore
- Ask clarifying questions when appropriate
- Use natural language, avoid bullet points for simple responses
- End with an invitation to continue: "Want me to dig deeper into any of these?"
""",
    "structured": """
## Response Style: Structured
- Be direct and efficient
- Use markdown formatting: headers, bullets, tables where appropriate
- Lead with the key finding/answer
- Organize information hierarchically
- Include specific quotes/data from sources
""",
    "report": """
## Response Style: Report
- Format as a professional report
- Include: Executive Summary, Key Findings, Details, Recommendations
- Use tables for comparative data
- Cite sources with specific references
- Be comprehensive but organized
"""
}

def build_system_prompt(..., response_style: str = "structured"):
    prompt_parts = [BASE_SYSTEM_PROMPT]
    # ... existing logic ...

    # Add style instructions
    if response_style in STYLE_INSTRUCTIONS:
        prompt_parts.append(STYLE_INSTRUCTIONS[response_style])

    return "\n".join(prompt_parts)
```

---

### 2.2 Cross-Resource Synthesis Tool

**Problem**: Current tools operate on individual resources. Users often want to compare or synthesize across multiple documents.

**Solution**: Add a `compare_resources` tool.

**Implementation**:
```python
COMPARE_RESOURCES_TOOL = {
    "name": "compare_resources",
    "description": """Compare or synthesize information across multiple resources.

Use when the user wants to:
- Compare data between files ("how do Q3 and Q4 sales compare?")
- Find common themes across documents
- Synthesize information from multiple sources
- Create a unified view of related data

This tool searches all specified resources and synthesizes the results.""",
    "input_schema": {
        "type": "object",
        "properties": {
            "resource_names": {
                "type": "array",
                "items": {"type": "string"},
                "description": "List of resource names to compare/synthesize"
            },
            "query": {
                "type": "string",
                "description": "What to compare or look for across the resources"
            },
            "comparison_type": {
                "type": "string",
                "enum": ["compare", "synthesize", "find_common", "find_differences"],
                "description": "Type of cross-resource analysis"
            }
        },
        "required": ["resource_names", "query"]
    }
}
```

**Tool Handler**:
```python
elif block.name == "compare_resources":
    resource_names = block.input.get("resource_names", [])
    query = block.input.get("query", "")
    comparison_type = block.input.get("comparison_type", "compare")

    # Search each resource
    all_results = {}
    for name in resource_names:
        resource = find_resource(name, resources)
        if resource:
            results = self.retriever.retrieve(
                query=query,
                namespace=resource.id,
                top_k=5
            )
            all_results[name] = results

    # Format for synthesis
    formatted = format_comparison_results(all_results, comparison_type)
    tool_results.append({
        "type": "tool_result",
        "tool_use_id": block.id,
        "content": formatted
    })
```

---

### 2.3 Self-Correction Loop

**Problem**: When search returns poor results, the agent just uses them anyway.

**Solution**: Add result quality assessment and automatic retry with reformulated queries.

**Implementation**:
```python
def search_with_retry(self, query: str, namespace: str, max_retries: int = 2) -> list:
    """Search with automatic retry on poor results."""
    results = self.retriever.retrieve(query=query, namespace=namespace, top_k=5)

    # Assess quality
    if not results or all(r.score < 0.3 for r in results):
        for attempt in range(max_retries):
            # Ask Claude to reformulate
            reformulated = self._reformulate_query(query, attempt)
            results = self.retriever.retrieve(query=reformulated, namespace=namespace, top_k=5)

            if results and any(r.score >= 0.3 for r in results):
                break

    return results

def _reformulate_query(self, original: str, attempt: int) -> str:
    """Use Claude to reformulate a failing search query."""
    strategies = [
        "Extract key nouns and technical terms only",
        "Broaden the query by removing specific constraints",
        "Use synonyms for the main concepts"
    ]

    response = self.client.messages.create(
        model="claude-3-haiku-20240307",
        max_tokens=100,
        messages=[{
            "role": "user",
            "content": f"Reformulate this search query using strategy: {strategies[attempt]}\n\nQuery: {original}\n\nReformulated query (just the query, nothing else):"
        }]
    )
    return response.content[0].text.strip()
```

---

### 2.4 Source Quality Scoring

**Problem**: All search results are treated equally. No consideration for recency, authority, or engagement.

**Solution**: Add quality scoring to search results.

**Implementation**:
```python
@dataclass
class ScoredResult:
    result: RetrievalResult
    semantic_score: float  # From vector search
    recency_score: float   # Based on document date
    engagement_score: float  # How often this resource is queried
    final_score: float

def score_results(results: list[RetrievalResult], resource_stats: dict) -> list[ScoredResult]:
    """Score results by multiple factors."""
    scored = []
    for r in results:
        resource_id = r.metadata.get("resource_id")

        # Semantic score (already have this)
        semantic = r.score

        # Recency (days since upload, normalized)
        upload_date = r.metadata.get("upload_date")
        days_old = (datetime.now() - upload_date).days if upload_date else 365
        recency = max(0, 1 - (days_old / 365))  # 1.0 for today, 0.0 for 1+ year old

        # Engagement (query count for this resource)
        query_count = resource_stats.get(resource_id, {}).get("query_count", 0)
        engagement = min(1.0, query_count / 10)  # Cap at 10 queries

        # Weighted final score
        final = (semantic * 0.6) + (recency * 0.2) + (engagement * 0.2)

        scored.append(ScoredResult(r, semantic, recency, engagement, final))

    return sorted(scored, key=lambda x: x.final_score, reverse=True)
```

---

## 3. Intent Detection Improvements

### 3.1 Multi-Intent Parsing

**Problem**: Users often ask compound questions but the router picks only one category.

**Solution**: Parse multiple intents and execute them in order.

**Implementation**:
```python
@dataclass
class Intent:
    category: str
    query: str  # The part of the message for this intent
    resource_hint: str | None
    priority: int  # Execution order

@dataclass
class RequestPlanV4(RequestPlanV3):
    # Multi-intent support
    intents: list[Intent] | None = None
    execution_mode: str = "sequential"  # "sequential" | "parallel"

# Router prompt addition:
"""
## MULTI-INTENT DETECTION

If the user's message contains multiple distinct requests, identify each one:

Example: "Find the sales data and also summarize the marketing report"
→ intents: [
    {"category": "doc_search", "query": "sales data", "priority": 1},
    {"category": "analysis", "query": "summarize marketing report", "priority": 2}
  ]
→ execution_mode: "sequential"

Example: "What's in my workspace and what's the weather?"
→ intents: [
    {"category": "resource_query", "query": "list workspace", "priority": 1},
    {"category": "web_search", "query": "current weather", "priority": 1}
  ]
→ execution_mode: "parallel" (independent queries)

Only use multi-intent for CLEARLY separate requests. Don't split natural compound sentences.
"""
```

---

### 3.2 Conversation Arc Tracking

**Problem**: The agent treats each message independently, missing the bigger picture of where the user is in their research.

**Solution**: Track conversation phase and adapt behavior accordingly.

**Implementation**:
```python
@dataclass
class ConversationState:
    phase: str  # "discovery", "exploration", "deep_dive", "synthesis", "conclusion"
    focus_resources: list[str]  # Resources user keeps returning to
    query_count_by_resource: dict[str, int]
    total_queries: int
    findings_saved: int
    last_category: str

def detect_conversation_phase(state: ConversationState, plan: RequestPlanV3) -> str:
    """Detect where user is in their research journey."""

    # Discovery: First few queries, exploring what's available
    if state.total_queries < 3:
        return "discovery"

    # Conclusion: Saving findings, wrapping up
    if plan.category == "save_finding" or state.findings_saved > 0:
        return "conclusion"

    # Deep dive: Same resource queried 3+ times
    max_queries = max(state.query_count_by_resource.values()) if state.query_count_by_resource else 0
    if max_queries >= 3:
        return "deep_dive"

    # Synthesis: Multiple resources with 2+ queries each
    multi_resource = sum(1 for c in state.query_count_by_resource.values() if c >= 2)
    if multi_resource >= 2:
        return "synthesis"

    return "exploration"

# Adapt behavior based on phase:
PHASE_BEHAVIORS = {
    "discovery": {
        "proactive_suggestions": True,
        "offer_resource_list": True,
        "response_length": "medium"
    },
    "exploration": {
        "proactive_suggestions": True,
        "suggest_related": True,
        "response_length": "medium"
    },
    "deep_dive": {
        "proactive_suggestions": False,  # User knows what they want
        "offer_analysis": True,
        "response_length": "detailed"
    },
    "synthesis": {
        "offer_comparison": True,
        "suggest_findings": True,
        "response_length": "comprehensive"
    },
    "conclusion": {
        "offer_export": True,
        "summarize_session": True,
        "response_length": "concise"
    }
}
```

---

### 3.3 Urgency Detection

**Problem**: All queries are treated with the same priority/thoroughness.

**Solution**: Detect urgency signals and adapt response accordingly.

**Implementation**:
```python
# Add to router prompt:
"""
## URGENCY DETECTION

Detect urgency level from language:

HIGH urgency (quick response, less thinking):
- "quick question", "real quick", "ASAP", "urgent"
- "just tell me", "simple answer", "yes or no"
- Very short messages (<10 words)
→ Set: complexity="simple", thinking_budget=0

LOW urgency (thorough response, more thinking):
- "thoroughly", "comprehensive", "detailed", "in depth"
- "take your time", "when you can", "no rush"
- "analyze carefully", "consider all aspects"
→ Set: complexity="complex", thinking_budget=10000

Add field: urgency: "high" | "normal" | "low"
"""

@dataclass
class RequestPlanV4(RequestPlanV3):
    urgency: str = "normal"  # "high", "normal", "low"
```

---

### 3.4 Implicit Reference Resolution

**Problem**: When user says "the document" or "that file", we rely on router guessing.

**Solution**: Track recently mentioned resources and resolve references.

**Implementation**:
```python
class ReferenceTracker:
    """Track recently mentioned resources for pronoun resolution."""

    def __init__(self, max_history: int = 5):
        self.recent_resources: list[tuple[str, float]] = []  # (name, timestamp)
        self.max_history = max_history

    def mention(self, resource_name: str):
        """Record that a resource was mentioned."""
        now = time.time()
        # Remove old mention of same resource
        self.recent_resources = [(n, t) for n, t in self.recent_resources if n != resource_name]
        # Add to front
        self.recent_resources.insert(0, (resource_name, now))
        # Trim
        self.recent_resources = self.recent_resources[:self.max_history]

    def resolve(self, reference: str) -> str | None:
        """Resolve a reference like 'it', 'the document', 'that file'."""
        if not self.recent_resources:
            return None

        # Patterns that refer to most recent resource
        recent_patterns = ["it", "that", "the file", "the document", "the data", "this"]
        if any(p in reference.lower() for p in recent_patterns):
            return self.recent_resources[0][0]

        return None

# Usage in router:
reference_tracker = ReferenceTracker()

# After each tool use on a resource:
if tool_name in ["search_documents", "analyze_data", "view_image", "read_resource"]:
    reference_tracker.mention(resource_name)

# In plan_request, check for implicit references:
resolved = reference_tracker.resolve(message)
if resolved:
    python_matched_resource = resolved
    python_match_confidence = 0.8
```

---

## 4. Implementation Priority

### Phase 1: Quick Wins (1-2 hours each)
1. **Adaptive system prompt** - Uses existing V3 `response_style`
2. **Regex pre-router** - Instant responses for obvious patterns
3. **Resource caching** - Simple TTL cache

### Phase 2: Medium Effort (half day each)
4. **Parallel tool execution** - Async/threading for tools
5. **Urgency detection** - Router prompt update + handling
6. **Implicit reference resolution** - Reference tracker class

### Phase 3: Larger Features (1+ day each)
7. **Conversation arc tracking** - State management + phase detection
8. **Multi-intent parsing** - Router changes + execution logic
9. **Cross-resource synthesis** - New tool + handler
10. **Self-correction loop** - Query reformulation + retry logic

---

## 5. Testing Checklist

- [ ] Parallel tools: Verify speedup with multi-tool queries
- [ ] Caching: Verify cache invalidation on resource add/delete
- [ ] Pre-router: Test all instant patterns match correctly
- [ ] Adaptive prompts: Compare response styles qualitatively
- [ ] Multi-intent: Test compound queries parse correctly
- [ ] Arc tracking: Verify phase transitions make sense
- [ ] Reference resolution: Test "it", "that", "the document" cases
- [ ] Self-correction: Verify retry improves poor results

---

## 6. Metrics to Track

| Metric | Current | Target |
|--------|---------|--------|
| Avg response time (simple query) | ~2s | <1s |
| Avg response time (tool query) | ~4s | <2.5s |
| User clarification rate | ? | -30% |
| Search result relevance | ? | +20% |
| Multi-resource queries handled | 0% | 80% |
