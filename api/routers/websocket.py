"""WebSocket endpoint for real-time job streaming.

Uses redis.asyncio for true async pub/sub - no polling, instant message delivery.
"""

import json
import asyncio
import os
from contextlib import asynccontextmanager
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
import redis.asyncio as aioredis

from api.database import SessionLocal, ConversationJob, JobStatus
from api.tasks import get_job_channel, get_job_state, redis_client

router = APIRouter(tags=["websocket"])

# Async Redis client for pub/sub (created lazily)
_async_redis: aioredis.Redis | None = None


async def get_async_redis() -> aioredis.Redis:
    """Get or create async Redis client."""
    global _async_redis
    if _async_redis is None:
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        _async_redis = aioredis.from_url(redis_url, decode_responses=True)
    return _async_redis


@asynccontextmanager
async def async_pubsub(channel: str):
    """Context manager for async Redis pub/sub subscription."""
    redis = await get_async_redis()
    pubsub = redis.pubsub()
    try:
        await pubsub.subscribe(channel)
        yield pubsub
    finally:
        await pubsub.unsubscribe(channel)
        await pubsub.close()


def get_project_jobs_channel(project_id: str) -> str:
    """Get the Redis pub/sub channel for project-wide job updates."""
    return f"project:{project_id}:jobs"


def get_global_jobs_channel() -> str:
    """Get the Redis pub/sub channel for global job updates (all projects)."""
    return "global:jobs"


def publish_global_job_update(project_id: str, thread_id: str, job_id: str, status: str):
    """Publish a job status update to the global channel."""
    try:
        channel = get_global_jobs_channel()
        message = json.dumps({
            "type": "job_update",
            "data": {
                "project_id": project_id,
                "thread_id": thread_id,
                "job_id": job_id,
                "status": status,
            }
        })
        redis_client.publish(channel, message)
    except Exception:
        # Redis not available - that's okay, WebSocket clients will poll for updates
        pass


def publish_project_job_update(project_id: str, thread_id: str, status: str):
    """Publish a job status update to the project channel."""
    try:
        channel = get_project_jobs_channel(project_id)
        message = json.dumps({
            "type": "job_update",
            "data": {
                "thread_id": thread_id,
                "status": status,
            }
        })
        redis_client.publish(channel, message)
    except Exception:
        # Redis not available - that's okay, WebSocket clients will poll for updates
        pass


@router.websocket("/ws/jobs/{job_id}")
async def job_stream(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for streaming job events.

    Uses async Redis pub/sub for instant message delivery (no polling).

    When a client connects:
    1. If job is completed/failed, send final state and close
    2. If job is pending/running, subscribe to Redis pub/sub and stream events
    3. Send any accumulated partial_response first (for late joiners)

    Events sent to client:
    - status: Job status changed (running, completed, failed)
    - chunk: Text chunk from the response
    - sources: Source documents found
    - thinking: Extended thinking content
    - plan: Router acknowledgment/plan
    - tool_call: Tool being called
    - tool_result: Tool call result
    - usage: Token usage stats
    - done: Job completed successfully
    - error: Job failed
    """
    await websocket.accept()

    db: Session = SessionLocal()

    try:
        # Load job from database
        job = db.query(ConversationJob).filter(ConversationJob.id == job_id).first()

        if not job:
            await websocket.send_json({"type": "error", "data": {"message": "Job not found"}})
            await websocket.close()
            return

        # If job is already completed, send final state
        if job.status == JobStatus.COMPLETED:
            sources = json.loads(job.sources_json) if job.sources_json else []
            await websocket.send_json({
                "type": "done",
                "data": {
                    "status": "completed",
                    "message_id": job.assistant_message_id,
                    "content": job.partial_response or "",
                    "sources": sources,
                }
            })
            await websocket.close()
            return

        if job.status == JobStatus.FAILED:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "status": "failed",
                    "message": job.error_message or "Unknown error"
                }
            })
            await websocket.close()
            return

        if job.status == JobStatus.CANCELLED:
            await websocket.send_json({
                "type": "error",
                "data": {
                    "status": "cancelled",
                    "message": "Job was cancelled"
                }
            })
            await websocket.close()
            return

        # Job is pending or running - send current accumulated state (late joiner support)
        state = get_job_state(job_id)
        await websocket.send_json({
            "type": "state",
            "data": {
                "status": job.status.value,
                "content": state.get("content", "") or job.partial_response or "",
                "sources": state.get("sources", []),
                "acknowledgment": state.get("acknowledgment", ""),
                "activity": state.get("activity", []),
                "thinking": state.get("thinking", ""),
            }
        })

        # Close DB session before long-running subscription
        db.close()
        db = None

        # Subscribe to Redis pub/sub with true async listener
        channel = get_job_channel(job_id)
        async with async_pubsub(channel) as pubsub:
            # Listen for messages - this is a true async iterator, no polling!
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await websocket.send_json(event)

                        # If done or error, close the connection
                        if event.get("type") in ("done", "error"):
                            break
                    except json.JSONDecodeError:
                        pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        if db:
            db.close()
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/ws/projects/{project_id}")
async def project_stream(websocket: WebSocket, project_id: str):
    """
    Unified WebSocket for a project - handles both sidebar indicators AND job streaming.

    Uses async Redis pub/sub for instant message delivery.

    Client messages:
    - { "type": "subscribe_thread", "thread_id": "..." } - Start watching a thread's job
    - { "type": "unsubscribe_thread" } - Stop watching current thread

    Server messages:
    - { "type": "active_jobs", "data": { "thread_ids": [...] } } - Initial active jobs (on connect)
    - { "type": "job_update", "data": { "thread_id": "...", "status": "..." } } - Job status changed
    - { "type": "job_state", "data": { ... } } - Full job state snapshot (when subscribing to thread)
    - { "type": "job_event", "data": { "event_type": "...", ... } } - Job events (only for subscribed thread)
    """
    await websocket.accept()

    db: Session = SessionLocal()
    subscribed_thread_id = None
    subscribed_job_id = None
    job_listener_task = None

    try:
        # Send initial list of active jobs for sidebar
        active_jobs = db.query(ConversationJob).filter(
            ConversationJob.project_id == project_id,
            ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
        ).all()

        active_thread_ids = [job.thread_id for job in active_jobs]
        await websocket.send_json({
            "type": "active_jobs",
            "data": {"thread_ids": active_thread_ids}
        })

        # Close DB early - will use short-lived sessions for queries
        db.close()
        db = None

        # Async task to listen for job events
        async def listen_job_events(job_id: str, thread_id: str):
            """Background task that listens for job events and forwards to WebSocket."""
            channel = get_job_channel(job_id)
            try:
                async with async_pubsub(channel) as pubsub:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            try:
                                event = json.loads(message["data"])
                                event_data = event.get("data", {})
                                await websocket.send_json({
                                    "type": "job_event",
                                    "data": {
                                        "type": event.get("type"),
                                        **event_data,
                                        "thread_id": thread_id,
                                    }
                                })
                                # If job done/error, exit listener
                                if event.get("type") in ("done", "error"):
                                    break
                            except json.JSONDecodeError:
                                pass
            except asyncio.CancelledError:
                pass

        # Subscribe to project-level job updates
        project_channel = get_project_jobs_channel(project_id)
        redis = await get_async_redis()
        project_pubsub = redis.pubsub()
        await project_pubsub.subscribe(project_channel)

        # Main event loop - concurrent listening
        async def listen_project_events():
            """Listen for project-level events (sidebar updates)."""
            async for message in project_pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await websocket.send_json(event)
                    except json.JSONDecodeError:
                        pass

        async def listen_client_messages():
            """Listen for client commands (subscribe/unsubscribe)."""
            nonlocal subscribed_thread_id, subscribed_job_id, job_listener_task

            while True:
                try:
                    client_msg = await websocket.receive_text()
                    data = json.loads(client_msg)
                    msg_type = data.get("type")

                    if msg_type == "subscribe_thread":
                        thread_id = data.get("thread_id")
                        if thread_id:
                            # Cancel existing job listener
                            if job_listener_task and not job_listener_task.done():
                                job_listener_task.cancel()
                                try:
                                    await job_listener_task
                                except asyncio.CancelledError:
                                    pass

                            subscribed_thread_id = thread_id

                            # Find active job for this thread (short-lived session)
                            job_db = SessionLocal()
                            try:
                                job = job_db.query(ConversationJob).filter(
                                    ConversationJob.thread_id == thread_id,
                                    ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
                                ).order_by(ConversationJob.created_at.desc()).first()

                                if job:
                                    subscribed_job_id = job.id
                                    state = get_job_state(job.id)
                                    await websocket.send_json({
                                        "type": "job_state",
                                        "data": {
                                            "job_id": job.id,
                                            "thread_id": thread_id,
                                            "status": job.status.value,
                                            "current_phase": state.get("current_phase", "initializing"),
                                            "current_action": state.get("current_action", ""),
                                            "content": state.get("content", "") or job.partial_response or "",
                                            "sources": state.get("sources", []),
                                            "thinking": state.get("thinking", ""),
                                            "activity": state.get("activity", []),
                                            "started_at": state.get("started_at", ""),
                                            "acknowledgment": state.get("acknowledgment", ""),
                                        }
                                    })
                                    # Start background listener for this job
                                    job_listener_task = asyncio.create_task(
                                        listen_job_events(job.id, thread_id)
                                    )
                                else:
                                    subscribed_job_id = None
                                    await websocket.send_json({
                                        "type": "job_state",
                                        "data": {
                                            "job_id": None,
                                            "thread_id": thread_id,
                                            "status": "idle",
                                            "current_phase": "idle",
                                            "current_action": "",
                                            "content": "",
                                            "sources": [],
                                            "activity": [],
                                            "thinking": "",
                                            "started_at": "",
                                        }
                                    })
                            finally:
                                job_db.close()

                    elif msg_type == "unsubscribe_thread":
                        if job_listener_task and not job_listener_task.done():
                            job_listener_task.cancel()
                            try:
                                await job_listener_task
                            except asyncio.CancelledError:
                                pass
                        subscribed_thread_id = None
                        subscribed_job_id = None
                        job_listener_task = None

                except json.JSONDecodeError:
                    pass

        # Run both listeners concurrently
        project_task = asyncio.create_task(listen_project_events())
        client_task = asyncio.create_task(listen_client_messages())

        try:
            # Wait for client disconnect (client_task will raise WebSocketDisconnect)
            await client_task
        except WebSocketDisconnect:
            pass
        finally:
            # Cleanup
            project_task.cancel()
            if job_listener_task and not job_listener_task.done():
                job_listener_task.cancel()
            try:
                await project_task
            except asyncio.CancelledError:
                pass
            if job_listener_task:
                try:
                    await job_listener_task
                except asyncio.CancelledError:
                    pass
            await project_pubsub.unsubscribe(project_channel)
            await project_pubsub.close()

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        if db:
            db.close()
        try:
            await websocket.close()
        except:
            pass


# DEPRECATED - keeping for migration, will be removed
@router.websocket("/ws/projects/{project_id}/active-jobs")
async def project_active_jobs_stream(websocket: WebSocket, project_id: str):
    """
    DEPRECATED: Use /ws/projects/{project_id} instead.
    """
    await websocket.accept()

    db: Session = SessionLocal()

    try:
        # Send initial list of active jobs
        active_jobs = db.query(ConversationJob).filter(
            ConversationJob.project_id == project_id,
            ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
        ).all()

        active_thread_ids = [job.thread_id for job in active_jobs]
        await websocket.send_json({
            "type": "initial",
            "data": {"active_thread_ids": active_thread_ids}
        })

        db.close()
        db = None

        # Subscribe with async pub/sub
        channel = get_project_jobs_channel(project_id)
        async with async_pubsub(channel) as pubsub:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    try:
                        event = json.loads(message["data"])
                        await websocket.send_json(event)
                    except json.JSONDecodeError:
                        pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        if db:
            db.close()
        try:
            await websocket.close()
        except:
            pass


def _get_active_jobs_data():
    """Get active jobs data using a short-lived database session."""
    db = SessionLocal()
    try:
        active_jobs = db.query(ConversationJob).filter(
            ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
        ).all()
        return [
            {
                "project_id": job.project_id,
                "thread_id": job.thread_id,
                "job_id": job.id,
                "status": job.status.value,
            }
            for job in active_jobs
        ]
    finally:
        db.close()


def _get_thread_active_job(thread_id: str):
    """Get active job for a thread using a short-lived database session."""
    db = SessionLocal()
    try:
        job = db.query(ConversationJob).filter(
            ConversationJob.thread_id == thread_id,
            ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
        ).order_by(ConversationJob.created_at.desc()).first()
        if job:
            return {
                "id": job.id,
                "status": job.status.value,
                "partial_response": job.partial_response,
            }
        return None
    finally:
        db.close()


@router.websocket("/ws/app")
async def app_stream(websocket: WebSocket):
    """
    App-level WebSocket - single connection for entire session, never disconnects.

    Uses async Redis pub/sub for instant message delivery (no polling).

    Stays connected across project and thread navigation. Handles:
    - Global job status updates (which threads have active jobs, across all projects)
    - Job streaming for the currently subscribed thread

    Client messages:
    - { "type": "subscribe_thread", "project_id": "...", "thread_id": "..." }
    - { "type": "unsubscribe_thread" }

    Server messages:
    - { "type": "active_jobs", "data": { "jobs": [{ project_id, thread_id, job_id, status }, ...] } }
    - { "type": "job_update", "data": { project_id, thread_id, job_id, status } }
    - { "type": "job_state", "data": { project_id, thread_id, job_id, status, content, sources, ... } }
    - { "type": "job_event", "data": { type, ... } }
    """
    await websocket.accept()

    subscribed_project_id = None
    subscribed_thread_id = None
    subscribed_job_id = None
    job_listener_task = None
    global_listener_task = None
    redis_available = True

    try:
        # Send initial list of ALL active jobs
        jobs_data = _get_active_jobs_data()
        await websocket.send_json({
            "type": "active_jobs",
            "data": {"jobs": jobs_data}
        })

        # Async task to listen for job events
        async def listen_job_events(job_id: str, project_id: str, thread_id: str):
            """Background task that listens for job events and forwards to WebSocket."""
            nonlocal subscribed_job_id
            channel = get_job_channel(job_id)
            try:
                async with async_pubsub(channel) as pubsub:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            try:
                                event = json.loads(message["data"])
                                event_data = event.get("data", {})
                                await websocket.send_json({
                                    "type": "job_event",
                                    "data": {
                                        "type": event.get("type"),
                                        **event_data,
                                        "job_id": job_id,
                                        "thread_id": thread_id,
                                    }
                                })
                                if event.get("type") in ("done", "error"):
                                    # Send idle state
                                    await websocket.send_json({
                                        "type": "job_state",
                                        "data": {
                                            "project_id": project_id,
                                            "thread_id": thread_id,
                                            "job_id": None,
                                            "status": "idle",
                                            "current_phase": "idle",
                                            "current_action": "",
                                            "content": "",
                                            "sources": [],
                                            "activity": [],
                                            "thinking": "",
                                            "started_at": "",
                                        }
                                    })
                                    subscribed_job_id = None
                                    break
                            except json.JSONDecodeError:
                                pass
            except asyncio.CancelledError:
                pass

        # Async task to listen for global job updates
        async def listen_global_events():
            """Listen for global job updates (all projects)."""
            global_channel = get_global_jobs_channel()
            try:
                async with async_pubsub(global_channel) as pubsub:
                    async for message in pubsub.listen():
                        if message["type"] == "message":
                            try:
                                event = json.loads(message["data"])
                                await websocket.send_json(event)
                            except json.JSONDecodeError:
                                pass
            except asyncio.CancelledError:
                pass
            except Exception:
                # Redis connection lost
                nonlocal redis_available
                redis_available = False

        # Start global listener
        global_listener_task = asyncio.create_task(listen_global_events())

        # Listen for client messages
        while True:
            try:
                client_msg = await websocket.receive_text()
                data = json.loads(client_msg)
                msg_type = data.get("type")

                if msg_type == "subscribe_thread":
                    project_id = data.get("project_id")
                    thread_id = data.get("thread_id")
                    if project_id and thread_id:
                        # Cancel existing job listener
                        if job_listener_task and not job_listener_task.done():
                            job_listener_task.cancel()
                            try:
                                await job_listener_task
                            except asyncio.CancelledError:
                                pass

                        subscribed_project_id = project_id
                        subscribed_thread_id = thread_id

                        # Get active job (short-lived session)
                        job_data = _get_thread_active_job(thread_id)

                        if job_data:
                            subscribed_job_id = job_data["id"]
                            state = get_job_state(job_data["id"])
                            await websocket.send_json({
                                "type": "job_state",
                                "data": {
                                    "project_id": project_id,
                                    "thread_id": thread_id,
                                    "job_id": job_data["id"],
                                    "status": job_data["status"],
                                    "current_phase": state.get("current_phase", "initializing"),
                                    "current_action": state.get("current_action", ""),
                                    "content": state.get("content", "") or job_data.get("partial_response") or "",
                                    "sources": state.get("sources", []),
                                    "thinking": state.get("thinking", ""),
                                    "activity": state.get("activity", []),
                                    "started_at": state.get("started_at", ""),
                                    "acknowledgment": state.get("acknowledgment", ""),
                                }
                            })

                            if redis_available:
                                job_listener_task = asyncio.create_task(
                                    listen_job_events(job_data["id"], project_id, thread_id)
                                )
                        else:
                            subscribed_job_id = None
                            await websocket.send_json({
                                "type": "job_state",
                                "data": {
                                    "project_id": project_id,
                                    "thread_id": thread_id,
                                    "job_id": None,
                                    "status": "idle",
                                    "current_phase": "idle",
                                    "current_action": "",
                                    "content": "",
                                    "sources": [],
                                    "activity": [],
                                    "thinking": "",
                                    "started_at": "",
                                }
                            })

                elif msg_type == "unsubscribe_thread":
                    if job_listener_task and not job_listener_task.done():
                        job_listener_task.cancel()
                        try:
                            await job_listener_task
                        except asyncio.CancelledError:
                            pass
                    subscribed_project_id = None
                    subscribed_thread_id = None
                    subscribed_job_id = None
                    job_listener_task = None

            except json.JSONDecodeError:
                pass

    except WebSocketDisconnect:
        pass
    except Exception as e:
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        # Cleanup all tasks
        if global_listener_task and not global_listener_task.done():
            global_listener_task.cancel()
            try:
                await global_listener_task
            except asyncio.CancelledError:
                pass
        if job_listener_task and not job_listener_task.done():
            job_listener_task.cancel()
            try:
                await job_listener_task
            except asyncio.CancelledError:
                pass
        try:
            await websocket.close()
        except:
            pass
