"""WebSocket endpoint for real-time job streaming."""

import json
import asyncio
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from api.database import SessionLocal, ConversationJob, JobStatus
from api.tasks import get_job_channel, get_job_state, redis_client

router = APIRouter(tags=["websocket"])


def get_project_jobs_channel(project_id: str) -> str:
    """Get the Redis pub/sub channel for project-wide job updates."""
    return f"project:{project_id}:jobs"


def publish_project_job_update(project_id: str, thread_id: str, status: str):
    """Publish a job status update to the project channel."""
    channel = get_project_jobs_channel(project_id)
    message = json.dumps({
        "type": "job_update",
        "data": {
            "thread_id": thread_id,
            "status": status,
        }
    })
    redis_client.publish(channel, message)


@router.websocket("/ws/jobs/{job_id}")
async def job_stream(websocket: WebSocket, job_id: str):
    """
    WebSocket endpoint for streaming job events.

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
    pubsub = None

    try:
        # Load job from database
        job = db.query(ConversationJob).filter(ConversationJob.id == job_id).first()

        if not job:
            await websocket.send_json({"type": "error", "data": {"message": "Job not found"}})
            await websocket.close()
            return

        # If job is already completed, send final state
        if job.status == JobStatus.COMPLETED:
            # Send the completed response
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

        # Job is pending or running - send current accumulated state
        # This gives late joiners the full picture immediately
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

        # Subscribe to Redis pub/sub for this job
        channel = get_job_channel(job_id)
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel)

        # Stream events from Redis to WebSocket
        while True:
            # Check for messages with a timeout
            message = pubsub.get_message(timeout=0.1)

            if message and message["type"] == "message":
                # Parse and forward the event to WebSocket
                try:
                    event = json.loads(message["data"])
                    await websocket.send_json(event)

                    # If done or error, close the connection
                    if event.get("type") in ("done", "error"):
                        break
                except json.JSONDecodeError:
                    pass

            # Small sleep to prevent busy loop
            await asyncio.sleep(0.01)

            # Check if websocket is still connected by trying to receive
            # (This handles client disconnection)
            try:
                # Non-blocking check for incoming messages (like ping/pong)
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.001
                )
            except asyncio.TimeoutError:
                # No message received, that's fine
                pass
            except WebSocketDisconnect:
                # Client disconnected
                break

    except WebSocketDisconnect:
        # Client disconnected - that's fine
        pass
    except Exception as e:
        # Send error to client if still connected
        try:
            await websocket.send_json({
                "type": "error",
                "data": {"message": str(e)}
            })
        except:
            pass
    finally:
        # Cleanup
        if pubsub:
            pubsub.unsubscribe()
            pubsub.close()
        db.close()
        try:
            await websocket.close()
        except:
            pass


@router.websocket("/ws/projects/{project_id}")
async def project_stream(websocket: WebSocket, project_id: str):
    """
    Unified WebSocket for a project - handles both sidebar indicators AND job streaming.

    This single connection stays open for the entire project session.
    Thread switching happens via messages, not reconnections.

    Client messages:
    - { "type": "subscribe_thread", "thread_id": "..." } - Start watching a thread's job
    - { "type": "unsubscribe_thread" } - Stop watching current thread

    Server messages:
    - { "type": "active_jobs", "data": { "thread_ids": [...] } } - Initial active jobs (on connect)
    - { "type": "job_update", "data": { "thread_id": "...", "status": "..." } } - Job status changed (always sent)
    - { "type": "job_state", "data": { ... } } - Full job state snapshot (when subscribing to thread)
    - { "type": "job_event", "data": { "event_type": "...", ... } } - Job events (only for subscribed thread)
    """
    await websocket.accept()

    db: Session = SessionLocal()
    project_pubsub = None
    job_pubsub = None
    subscribed_thread_id = None
    subscribed_job_id = None

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

        # Subscribe to project-level job updates (for sidebar)
        project_channel = get_project_jobs_channel(project_id)
        project_pubsub = redis_client.pubsub()
        project_pubsub.subscribe(project_channel)

        # Main event loop
        while True:
            # Check for project-level updates (job_update events for sidebar)
            project_msg = project_pubsub.get_message(timeout=0.05)
            if project_msg and project_msg["type"] == "message":
                try:
                    event = json.loads(project_msg["data"])
                    # Always forward job_update events (for sidebar indicators)
                    await websocket.send_json(event)
                except json.JSONDecodeError:
                    pass

            # Check for job-specific events (only if subscribed to a thread)
            if job_pubsub:
                job_msg = job_pubsub.get_message(timeout=0.05)
                if job_msg and job_msg["type"] == "message":
                    try:
                        event = json.loads(job_msg["data"])
                        # Wrap job events so frontend knows it's for the subscribed thread
                        await websocket.send_json({
                            "type": "job_event",
                            "data": event
                        })
                        # If job is done/error, unsubscribe from job channel
                        if event.get("type") in ("done", "error"):
                            job_pubsub.unsubscribe()
                            job_pubsub.close()
                            job_pubsub = None
                            subscribed_job_id = None
                    except json.JSONDecodeError:
                        pass

            # Check for client messages (subscribe/unsubscribe)
            try:
                client_msg = await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.01
                )
                try:
                    data = json.loads(client_msg)
                    msg_type = data.get("type")

                    if msg_type == "subscribe_thread":
                        thread_id = data.get("thread_id")
                        if thread_id:
                            # Unsubscribe from old job if any
                            if job_pubsub:
                                job_pubsub.unsubscribe()
                                job_pubsub.close()
                                job_pubsub = None

                            subscribed_thread_id = thread_id

                            # Find active job for this thread
                            job = db.query(ConversationJob).filter(
                                ConversationJob.thread_id == thread_id,
                                ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
                            ).order_by(ConversationJob.created_at.desc()).first()

                            if job:
                                subscribed_job_id = job.id

                                # Send current job state snapshot
                                state = get_job_state(job.id)
                                await websocket.send_json({
                                    "type": "job_state",
                                    "data": {
                                        "job_id": job.id,
                                        "thread_id": thread_id,
                                        "status": job.status.value,
                                        "content": state.get("content", "") or job.partial_response or "",
                                        "sources": state.get("sources", []),
                                        "acknowledgment": state.get("acknowledgment", ""),
                                        "activity": state.get("activity", []),
                                        "thinking": state.get("thinking", ""),
                                    }
                                })

                                # Subscribe to job channel for real-time events
                                job_channel = get_job_channel(job.id)
                                job_pubsub = redis_client.pubsub()
                                job_pubsub.subscribe(job_channel)
                            else:
                                # No active job for this thread
                                await websocket.send_json({
                                    "type": "job_state",
                                    "data": {
                                        "job_id": None,
                                        "thread_id": thread_id,
                                        "status": "idle",
                                    }
                                })

                    elif msg_type == "unsubscribe_thread":
                        if job_pubsub:
                            job_pubsub.unsubscribe()
                            job_pubsub.close()
                            job_pubsub = None
                        subscribed_thread_id = None
                        subscribed_job_id = None

                except json.JSONDecodeError:
                    pass

            except asyncio.TimeoutError:
                # No client message, that's fine
                pass
            except WebSocketDisconnect:
                break

            await asyncio.sleep(0.01)

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
        if project_pubsub:
            project_pubsub.unsubscribe()
            project_pubsub.close()
        if job_pubsub:
            job_pubsub.unsubscribe()
            job_pubsub.close()
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
    WebSocket endpoint for streaming active job updates for a project.
    """
    await websocket.accept()

    db: Session = SessionLocal()
    pubsub = None

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

        # Subscribe to project job updates channel
        channel = get_project_jobs_channel(project_id)
        pubsub = redis_client.pubsub()
        pubsub.subscribe(channel)

        # Stream updates
        while True:
            message = pubsub.get_message(timeout=0.1)

            if message and message["type"] == "message":
                try:
                    event = json.loads(message["data"])
                    await websocket.send_json(event)
                except json.JSONDecodeError:
                    pass

            await asyncio.sleep(0.01)

            # Check for client disconnect
            try:
                await asyncio.wait_for(
                    websocket.receive_text(),
                    timeout=0.001
                )
            except asyncio.TimeoutError:
                pass
            except WebSocketDisconnect:
                break

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
        if pubsub:
            pubsub.unsubscribe()
            pubsub.close()
        db.close()
        try:
            await websocket.close()
        except:
            pass
