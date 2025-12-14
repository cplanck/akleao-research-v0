"""Job management API routes for persistent conversations."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from pydantic import BaseModel

from api.database import (
    get_db, Project, Thread, Message, ConversationJob,
    JobStatus, MessageRole, User
)
from api.middleware.auth import get_current_user
from api.tasks.conversation import process_conversation_task
from api.routers.websocket import publish_global_job_update, publish_project_job_update

router = APIRouter(tags=["jobs"])


# Request/Response models
class JobCreateRequest(BaseModel):
    question: str
    context_only: bool = False
    start_immediately: bool = False  # If True, start Celery task immediately (for background processing)


class JobResponse(BaseModel):
    id: str
    thread_id: str
    project_id: str
    status: str
    user_message_content: str
    partial_response: str | None = None
    sources_json: str | None = None
    assistant_message_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    token_count: int | None = None
    duration_ms: int | None = None

    class Config:
        from_attributes = True


def _job_to_response(job: ConversationJob) -> JobResponse:
    """Convert a ConversationJob to a JobResponse."""
    return JobResponse(
        id=job.id,
        thread_id=job.thread_id,
        project_id=job.project_id,
        status=job.status.value,
        user_message_content=job.user_message_content,
        partial_response=job.partial_response,
        sources_json=job.sources_json,
        assistant_message_id=job.assistant_message_id,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        token_count=job.token_count,
        duration_ms=job.duration_ms,
    )


class ActiveThreadJob(BaseModel):
    """Minimal job info for sidebar indicators."""
    thread_id: str
    job_id: str
    status: str


@router.get("/projects/{project_id}/jobs/active", response_model=list[ActiveThreadJob])
def get_project_active_jobs(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Get all active (pending/running) jobs for a project.

    Returns a list of thread IDs that have active jobs.
    This is used for showing indicators in the thread sidebar.
    """
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Find all active jobs for this project
    jobs = db.query(ConversationJob).filter(
        ConversationJob.project_id == project_id,
        ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
    ).all()

    return [
        ActiveThreadJob(
            thread_id=job.thread_id,
            job_id=job.id,
            status=job.status.value
        )
        for job in jobs
    ]


@router.post("/projects/{project_id}/threads/{thread_id}/jobs", response_model=JobResponse)
def create_job(
    project_id: str,
    thread_id: str,
    request: JobCreateRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Create a new conversation job.

    This endpoint:
    1. Validates the project and thread exist
    2. Creates and saves the user message
    3. Creates a ConversationJob record
    4. Enqueues the Celery task to process the conversation
    5. Returns immediately with the job details

    The frontend can then poll for job status to see progress.
    """
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify thread exists and belongs to project
    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Create user message
    user_message = Message(
        thread_id=thread_id,
        role=MessageRole.USER,
        content=request.question
    )
    db.add(user_message)
    db.commit()
    db.refresh(user_message)

    # Create conversation job
    job = ConversationJob(
        thread_id=thread_id,
        project_id=project_id,
        status=JobStatus.PENDING,
        user_message_id=user_message.id,
        user_message_content=request.question,
        context_only=1 if request.context_only else 0,
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    # Publish job creation to WebSocket channels for real-time UI updates
    publish_project_job_update(project_id, thread_id, "pending")
    publish_global_job_update(project_id, thread_id, job.id, "pending")

    # Only enqueue Celery task if start_immediately is True
    # Otherwise, frontend will use SSE streaming and call /start if user navigates away
    if request.start_immediately:
        process_conversation_task.delay(job.id)

    return _job_to_response(job)


# NOTE: /jobs/active MUST be defined before /jobs/{job_id} to avoid route conflicts
@router.get("/projects/{project_id}/threads/{thread_id}/jobs/active")
def get_active_job(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Get the currently active (pending/running) job for a thread.

    Returns null if there's no active job. This is useful when the user
    returns to a thread to check if there's work in progress.
    """
    # Verify project belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Find active job (pending or running)
    job = db.query(ConversationJob).filter(
        ConversationJob.thread_id == thread_id,
        ConversationJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING])
    ).order_by(ConversationJob.created_at.desc()).first()

    if not job:
        # Return explicit null JSON response
        return JSONResponse(content=None)

    # Update last_polled_at
    job.last_polled_at = datetime.utcnow()
    db.commit()

    return _job_to_response(job)


@router.get("/projects/{project_id}/threads/{thread_id}/jobs/{job_id}", response_model=JobResponse)
def get_job(
    project_id: str,
    thread_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Get job status and partial response.

    This endpoint also updates `last_polled_at` to track whether the user
    is actively watching the job (used for notification logic).
    """
    # Verify project belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Get job
    job = db.query(ConversationJob).filter(
        ConversationJob.id == job_id,
        ConversationJob.thread_id == thread_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update last_polled_at to track user presence
    job.last_polled_at = datetime.utcnow()
    db.commit()

    return _job_to_response(job)


@router.post("/projects/{project_id}/threads/{thread_id}/jobs/{job_id}/start", response_model=JobResponse)
def start_job(
    project_id: str,
    thread_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Start a pending job via Celery.

    This is called when the user navigates away while SSE streaming is in progress.
    The Celery worker will pick up where the streaming left off.

    If the job is already running, this is a no-op and returns success.
    """
    # Get job
    job = db.query(ConversationJob).filter(
        ConversationJob.id == job_id,
        ConversationJob.thread_id == thread_id,
        ConversationJob.project_id == project_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # If already running or completed, just return success (idempotent)
    if job.status == JobStatus.RUNNING:
        return _job_to_response(job)

    if job.status in [JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED]:
        # Job already finished, return its final state
        return _job_to_response(job)

    # Only enqueue if pending
    if job.status == JobStatus.PENDING:
        # Enqueue Celery task
        process_conversation_task.delay(job.id)

    return _job_to_response(job)


class JobUpdateProgressRequest(BaseModel):
    partial_response: str
    sources_json: str | None = None


class JobCompleteRequest(BaseModel):
    assistant_message_id: str
    partial_response: str
    sources_json: str | None = None
    token_count: int | None = None
    duration_ms: int | None = None


@router.patch("/projects/{project_id}/threads/{thread_id}/jobs/{job_id}/progress", response_model=JobResponse)
def update_job_progress(
    project_id: str,
    thread_id: str,
    job_id: str,
    request: JobUpdateProgressRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Update job progress (partial response) before handing off to Celery.

    Called when user navigates away during SSE streaming to save progress.
    """
    job = db.query(ConversationJob).filter(
        ConversationJob.id == job_id,
        ConversationJob.thread_id == thread_id,
        ConversationJob.project_id == project_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    job.partial_response = request.partial_response
    if request.sources_json:
        job.sources_json = request.sources_json
    db.commit()

    return _job_to_response(job)


@router.post("/projects/{project_id}/threads/{thread_id}/jobs/{job_id}/complete", response_model=JobResponse)
def complete_job(
    project_id: str,
    thread_id: str,
    job_id: str,
    request: JobCompleteRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Mark a job as completed after SSE streaming finishes successfully.

    This is called by the frontend when SSE streaming completes normally,
    so we don't need to process it via Celery.
    """
    # Get job
    job = db.query(ConversationJob).filter(
        ConversationJob.id == job_id,
        ConversationJob.thread_id == thread_id,
        ConversationJob.project_id == project_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Update job with completion data
    job.status = JobStatus.COMPLETED
    job.assistant_message_id = request.assistant_message_id
    job.partial_response = request.partial_response
    job.sources_json = request.sources_json
    job.token_count = request.token_count
    job.duration_ms = request.duration_ms
    job.completed_at = datetime.utcnow()
    if job.started_at:
        job.duration_ms = int((job.completed_at - job.started_at).total_seconds() * 1000)
    db.commit()

    return _job_to_response(job)


@router.delete("/projects/{project_id}/threads/{thread_id}/jobs/{job_id}")
def cancel_job(
    project_id: str,
    thread_id: str,
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """
    Cancel a pending or running job.

    This sets the job status to CANCELLED and revokes the Celery task.
    """
    # Verify project belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    # Get job
    job = db.query(ConversationJob).filter(
        ConversationJob.id == job_id,
        ConversationJob.thread_id == thread_id
    ).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Can only cancel pending or running jobs
    if job.status not in [JobStatus.PENDING, JobStatus.RUNNING]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job with status '{job.status.value}'"
        )

    # Revoke Celery task if it has one
    if job.celery_task_id:
        from api.tasks import celery_app
        celery_app.control.revoke(job.celery_task_id, terminate=True)

    # Update job status
    job.status = JobStatus.CANCELLED
    job.completed_at = datetime.utcnow()
    db.commit()

    return {"status": "cancelled", "job_id": job_id}
