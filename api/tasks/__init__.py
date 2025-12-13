"""Celery task configuration for background job processing."""

import os
import json
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
    """
    event = {
        "type": event_type,
        "data": data or {}
    }
    message = json.dumps(event)

    state_key = get_job_state_key(job_id)

    # Update accumulated state based on event type
    if event_type == "plan":
        # Store the acknowledgment
        redis_client.hset(state_key, "acknowledgment", data.get("acknowledgment", ""))
    elif event_type == "chunk":
        # Append to accumulated content
        current = redis_client.hget(state_key, "content") or ""
        redis_client.hset(state_key, "content", current + data.get("content", ""))
    elif event_type == "sources":
        # Store sources
        redis_client.hset(state_key, "sources", json.dumps(data.get("sources", [])))
    elif event_type == "tool_call":
        # Append to activity log
        activity = redis_client.hget(state_key, "activity") or "[]"
        activity_list = json.loads(activity)
        activity_list.append({"type": "tool_call", **data})
        redis_client.hset(state_key, "activity", json.dumps(activity_list))
    elif event_type == "tool_result":
        # Append to activity log
        activity = redis_client.hget(state_key, "activity") or "[]"
        activity_list = json.loads(activity)
        activity_list.append({"type": "tool_result", **data})
        redis_client.hset(state_key, "activity", json.dumps(activity_list))
    elif event_type == "status":
        redis_client.hset(state_key, "status", data.get("status", ""))
    elif event_type == "thinking":
        # Append thinking content
        current = redis_client.hget(state_key, "thinking") or ""
        redis_client.hset(state_key, "thinking", current + data.get("content", ""))

    # Set TTL of 1 hour on the state
    redis_client.expire(state_key, 3600)

    # Publish to channel for real-time subscribers
    channel = get_job_channel(job_id)
    redis_client.publish(channel, message)


def get_job_state(job_id: str) -> dict:
    """
    Get the accumulated state for a job.

    Returns dict with: content, sources, acknowledgment, activity, status, thinking
    """
    state_key = get_job_state_key(job_id)
    raw_state = redis_client.hgetall(state_key)

    state = {
        "content": raw_state.get("content", ""),
        "acknowledgment": raw_state.get("acknowledgment", ""),
        "status": raw_state.get("status", ""),
        "thinking": raw_state.get("thinking", ""),
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
    "simage_tasks",
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
