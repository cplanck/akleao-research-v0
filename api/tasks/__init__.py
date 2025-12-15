"""Celery task configuration for background job processing."""

import os
import json
import time
import uuid
import redis
from celery import Celery
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Redis URL for Celery broker and backend
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Redis client for pub/sub streaming
redis_client = redis.from_url(redis_url, decode_responses=True)


def get_job_channel(job_id: str) -> str:
    """Get the Redis pub/sub channel name for a job."""
    return f"job:{job_id}:stream"


def get_job_state_key(job_id: str) -> str:
    """Get the Redis hash key for storing job state."""
    return f"job:{job_id}:state"


def publish_job_event(job_id: str, event_type: str, data: dict = None):
    """
    Publish an event to the job's Redis channel AND update accumulated state.

    State is stored in Redis so late joiners can see the current state immediately.
    Uses Redis pipelines to batch operations and reduce round-trips for lower latency.

    The agent state includes:
    - current_phase: What phase the agent is in (initializing, planning, searching, thinking, responding, done)
    - current_action: Human-readable description of what the agent is doing right now
    - activity: Full history of tool calls, results, and phase changes
    - content, sources, thinking: Accumulated output
    """
    event = {
        "type": event_type,
        "data": data or {}
    }
    message = json.dumps(event)

    state_key = get_job_state_key(job_id)
    channel = get_job_channel(job_id)
    data = data or {}

    # Use pipeline to batch Redis operations for lower latency
    pipe = redis_client.pipeline()

    # Update accumulated state based on event type
    if event_type == "phase":
        # Explicit phase update
        pipe.hset(state_key, "current_phase", data.get("phase", ""))
        pipe.hset(state_key, "current_action", data.get("action", ""))
        # Also add to activity history - need to read first
        activity = redis_client.hget(state_key, "activity") or "[]"
        activity_list = json.loads(activity)
        activity_list.append({
            "id": str(uuid.uuid4()),
            "type": "phase_change",
            "timestamp": time.time(),
            "phase": data.get("phase", ""),
            "action": data.get("action", ""),
        })
        pipe.hset(state_key, "activity", json.dumps(activity_list))

    elif event_type == "plan":
        # Plan event sets phase to "planning" and stores the acknowledgment as current_action
        pipe.hset(state_key, mapping={
            "current_phase": "planning",
            "current_action": data.get("acknowledgment", ""),
            "acknowledgment": data.get("acknowledgment", ""),  # backwards compat
        })

    elif event_type == "chunk":
        # First chunk moves to "responding" phase
        # For chunks, we need current state so fetch it first
        current_phase = redis_client.hget(state_key, "current_phase")
        current_content = redis_client.hget(state_key, "content") or ""
        updates = {"content": current_content + data.get("content", "")}
        if current_phase != "responding":
            updates["current_phase"] = "responding"
            updates["current_action"] = ""
        pipe.hset(state_key, mapping=updates)

    elif event_type == "sources":
        # Store sources
        pipe.hset(state_key, "sources", json.dumps(data.get("sources", [])))

    elif event_type == "tool_call":
        # Tool call sets phase to "searching"
        tool_name = data.get("tool", data.get("name", "documents"))
        query = data.get("query", "")
        # Fetch activity log and update atomically
        activity = redis_client.hget(state_key, "activity") or "[]"
        activity_list = json.loads(activity)
        activity_list.append({
            "id": data.get("id", str(uuid.uuid4())),
            "type": "tool_call",
            "timestamp": time.time(),
            "name": tool_name,
            "tool": tool_name,
            "query": query,
            "input": data.get("input"),
        })
        pipe.hset(state_key, mapping={
            "current_phase": "searching",
            "current_action": f"Searching {tool_name}",
            "activity": json.dumps(activity_list),
        })

    elif event_type == "tool_result":
        # Tool result - update activity and change phase
        activity = redis_client.hget(state_key, "activity") or "[]"
        activity_list = json.loads(activity)
        activity_list.append({
            "id": str(uuid.uuid4()),
            "type": "tool_result",
            "timestamp": time.time(),
            "tool": data.get("tool"),
            "query": data.get("query", ""),
            "tool_call_id": data.get("tool_call_id"),
            "found": data.get("found"),
        })
        pipe.hset(state_key, mapping={
            "current_phase": "thinking",
            "current_action": "Processing results",
            "activity": json.dumps(activity_list),
        })

    elif event_type == "status":
        status = data.get("status", "")
        pipe.hset(state_key, "status", status)
        # If status is "running" and no phase set yet, initialize
        if status == "running":
            current_phase = redis_client.hget(state_key, "current_phase")
            if not current_phase:
                pipe.hset(state_key, mapping={
                    "current_phase": "initializing",
                    "current_action": "",
                })
            # Set started_at if not already set
            if not redis_client.hget(state_key, "started_at"):
                pipe.hset(state_key, "started_at", str(time.time()))

    elif event_type == "thinking":
        # Extended thinking - set phase to "thinking"
        current_thinking = redis_client.hget(state_key, "thinking") or ""
        pipe.hset(state_key, mapping={
            "current_phase": "thinking",
            "current_action": "Deep thinking",
            "thinking": current_thinking + data.get("content", ""),
        })

    # Set TTL of 1 hour on the state and publish to channel
    pipe.expire(state_key, 3600)
    pipe.publish(channel, message)

    # Execute all batched operations in a single round-trip
    pipe.execute()


def get_job_state(job_id: str) -> dict:
    """
    Get the accumulated state for a job.

    Returns dict with:
    - current_phase: What phase the agent is in
    - current_action: Human-readable description of current action
    - content, sources, thinking: Accumulated output
    - activity: Full history of tool calls, results, phase changes
    - started_at: Unix timestamp when job started
    - status, acknowledgment: For backwards compatibility
    """
    state_key = get_job_state_key(job_id)
    raw_state = redis_client.hgetall(state_key)

    state = {
        "content": raw_state.get("content", ""),
        "current_phase": raw_state.get("current_phase", "initializing"),
        "current_action": raw_state.get("current_action", ""),
        "acknowledgment": raw_state.get("acknowledgment", ""),  # backwards compat
        "status": raw_state.get("status", ""),
        "thinking": raw_state.get("thinking", ""),
        "started_at": raw_state.get("started_at", ""),
        "sources": [],
        "activity": [],
    }

    # Parse JSON fields
    if raw_state.get("sources"):
        try:
            state["sources"] = json.loads(raw_state["sources"])
        except json.JSONDecodeError:
            pass

    if raw_state.get("activity"):
        try:
            state["activity"] = json.loads(raw_state["activity"])
        except json.JSONDecodeError:
            pass

    return state


def clear_job_state(job_id: str):
    """Clear the job state from Redis (called when job completes)."""
    state_key = get_job_state_key(job_id)
    redis_client.delete(state_key)

# Create Celery app
celery_app = Celery(
    "akleao_tasks",
    broker=redis_url,
    backend=redis_url,
    include=["api.tasks.conversation"],  # Include task modules
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",

    # Timezone
    timezone="UTC",
    enable_utc=True,

    # Task tracking
    task_track_started=True,

    # Timeouts (10 minute hard limit for conversations)
    task_time_limit=600,
    task_soft_time_limit=540,  # 9 minutes soft limit allows cleanup

    # Result expiry (keep results for 1 hour)
    result_expires=3600,

    # Worker settings
    worker_prefetch_multiplier=1,  # Process one task at a time
    worker_concurrency=4,  # 4 workers by default
)
