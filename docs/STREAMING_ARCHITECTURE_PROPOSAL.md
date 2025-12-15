# Streaming Architecture Proposal: State of the Art

## Current Issues

### 1. Direct SSE Path (query.py)
- Uses `threading.Thread` + `queue.Queue` to bridge sync agent to async SSE
- Queue polling with 100ms timeout adds latency
- Blocking sync operations in thread prevent true streaming

### 2. Background Job Path (conversation.py + websocket.py)
- Celery dispatch adds ~50-200ms initial latency
- Redis pub/sub polling (now 10ms, was 50-100ms)
- Multiple serialization hops

## Proposed State of the Art Architecture

### Option A: Async-Native Direct Streaming (Recommended)

```
Frontend ←──SSE──← FastAPI ←──async stream──← Anthropic API
                      │
                      └──async──→ Database (persistence)
```

**Key Changes:**
1. Use Anthropic's async client
2. Async generator that yields directly from API stream
3. Fire-and-forget async persistence (don't block stream)

**Implementation:**

```python
from anthropic import AsyncAnthropic
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import asyncio

client = AsyncAnthropic()

@router.post("/projects/{project_id}/threads/{thread_id}/query/stream")
async def query_stream(project_id: str, thread_id: str, request: QueryRequest):
    """True async streaming - no threads, no queues."""

    async def generate():
        accumulated_content = ""

        async with client.messages.stream(
            model="claude-sonnet-4-20250514",
            max_tokens=4096,
            messages=messages,
        ) as stream:
            async for event in stream:
                if event.type == "content_block_delta":
                    chunk = event.delta.text
                    accumulated_content += chunk
                    yield f"data: {json.dumps({'type': 'chunk', 'content': chunk})}\n\n"

        # After stream completes, persist to DB (non-blocking to client)
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

        # Fire-and-forget persistence
        asyncio.create_task(save_message(thread_id, accumulated_content))

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
    )

async def save_message(thread_id: str, content: str):
    """Async database persistence."""
    async with async_session() as session:
        message = Message(thread_id=thread_id, content=content, role="assistant")
        session.add(message)
        await session.commit()
```

**Benefits:**
- Zero polling latency
- Direct stream from Anthropic to client
- Async DB writes don't block streaming
- Simpler architecture (no Redis for hot path)

### Option B: Hybrid Architecture (For Background Jobs)

Keep background jobs for:
- Long-running tasks that might timeout
- Users who close the browser mid-stream
- Notification system

But use WebSocket with **proper async Redis**:

```python
import redis.asyncio as aioredis

# Use actual async pub/sub, not polling
async def websocket_endpoint(websocket: WebSocket, job_id: str):
    await websocket.accept()

    redis = aioredis.from_url("redis://localhost")
    pubsub = redis.pubsub()
    await pubsub.subscribe(f"job:{job_id}:stream")

    # True async - waits for messages, no polling
    async for message in pubsub.listen():
        if message["type"] == "message":
            await websocket.send_text(message["data"])
```

## Migration Path

### Phase 1: Quick Win (Current Changes)
- ✅ Reduce Redis polling to 10ms
- ✅ Reduce sleep to 1ms
- ✅ Batch Redis operations
- ✅ Increase DB save interval

### Phase 2: Direct Async Streaming
1. Create async version of Agent.chat_stream_events()
2. Update /query/stream to use async generator
3. Remove threading/queue bridge
4. Add async DB persistence

### Phase 3: Async Redis (If Keeping Background Jobs)
1. Switch to redis.asyncio
2. Use async pub/sub listeners
3. Remove all polling

## Performance Comparison

| Approach | First Chunk Latency | Per-Chunk Latency |
|----------|--------------------|--------------------|
| Current (thread + queue) | ~200-400ms | ~100ms |
| Current (Celery + Redis) | ~300-600ms | ~50-100ms |
| **Async Direct (proposed)** | ~100-200ms | ~0-5ms |
| **Async Redis (proposed)** | ~150-250ms | ~5-10ms |

## Recommended Priority

1. **High Impact, Low Effort**: Convert `/query/stream` to async
   - Remove threading
   - Use async Anthropic client
   - Biggest latency reduction

2. **Medium Impact**: Async Redis for WebSocket
   - Only if background jobs are essential
   - Use redis.asyncio with proper pub/sub

3. **Low Priority**: Keep Celery for
   - Very long tasks (>5 min)
   - Crash recovery
   - Offline notifications
