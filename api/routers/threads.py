"""Thread API routes."""

import os
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session
from anthropic import Anthropic
from dotenv import load_dotenv

from sqlalchemy import func

from api.database import get_db, Project, Thread, Message, User
from api.schemas import ThreadCreate, ThreadUpdate, ThreadResponse, ThreadDetail, MessageResponse
from api.middleware.auth import get_current_user


def get_child_count(db: Session, thread_id: str) -> int:
    """Get the number of child threads for a thread."""
    return db.query(Thread).filter(
        Thread.parent_thread_id == thread_id,
        Thread.deleted_at.is_(None)
    ).count()

load_dotenv()

router = APIRouter(tags=["threads"])


# Request schema for generating title
class GenerateTitleRequest(BaseModel):
    message: str


def generate_thread_title(message: str) -> str:
    """Use AI to generate a short, contextual thread title from a message.

    Uses Claude Haiku for fast, cheap title generation.
    """
    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=50,
            system="""Generate a very short (2-5 words) thread title that captures what the user is asking about.

Rules:
- Be specific to their actual question/topic
- Use title case
- No punctuation at the end
- No quotes around the title
- Just output the title, nothing else

Examples:
- "What invoices do we have for Chris?" → "Chris's Invoices"
- "Tell me about authentication" → "Authentication Overview"
- "How do I set up the database?" → "Database Setup"
- "Find errors in the logs" → "Log Errors"
- "What's the pricing for the pro plan?" → "Pro Plan Pricing"
""",
            messages=[{"role": "user", "content": message}]
        )

        title = response.content[0].text.strip()
        # Clean up: remove quotes if present, limit length
        title = title.strip('"\'')
        if len(title) > 50:
            title = title[:47] + "..."
        return title
    except Exception as e:
        print(f"[Thread Title] Error generating title: {e}")
        # Fallback: use first few words of message
        words = message.split()[:5]
        return " ".join(words) + ("..." if len(words) == 5 else "")


@router.post("/projects/{project_id}/threads", response_model=ThreadResponse)
def create_thread(
    project_id: str,
    thread: ThreadCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a new thread in a project.

    Can create child threads by providing parent_thread_id and parent_message_id.
    """
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate parent thread exists if provided
    if thread.parent_thread_id:
        parent = db.query(Thread).filter(
            Thread.id == thread.parent_thread_id,
            Thread.project_id == project_id,
            Thread.deleted_at.is_(None)
        ).first()
        if not parent:
            raise HTTPException(status_code=404, detail="Parent thread not found")

    # Validate parent message exists if provided
    if thread.parent_message_id:
        parent_message = db.query(Message).filter(
            Message.id == thread.parent_message_id
        ).first()
        if not parent_message:
            raise HTTPException(status_code=404, detail="Parent message not found")

    # Auto-generate title if not provided
    title = thread.title or "New Thread"

    db_thread = Thread(
        project_id=project_id,
        title=title,
        parent_thread_id=thread.parent_thread_id,
        parent_message_id=thread.parent_message_id,
        context_text=thread.context_text
    )
    db.add(db_thread)
    db.commit()
    db.refresh(db_thread)

    # Update project's last_thread_id
    project.last_thread_id = db_thread.id
    db.commit()

    return ThreadResponse(
        id=db_thread.id,
        project_id=db_thread.project_id,
        title=db_thread.title,
        created_at=db_thread.created_at,
        updated_at=db_thread.updated_at,
        parent_thread_id=db_thread.parent_thread_id,
        context_text=db_thread.context_text,
        child_count=0  # New thread has no children
    )


@router.get("/projects/{project_id}/threads", response_model=list[ThreadResponse])
def list_threads(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all active threads in a project."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Subquery to count children for each thread (avoids N+1 query problem)
    from sqlalchemy.orm import aliased
    ChildThread = aliased(Thread)
    child_count_subquery = (
        db.query(
            ChildThread.parent_thread_id,
            func.count(ChildThread.id).label("child_count")
        )
        .filter(
            ChildThread.project_id == project_id,
            ChildThread.deleted_at.is_(None),
            ChildThread.parent_thread_id.isnot(None)
        )
        .group_by(ChildThread.parent_thread_id)
        .subquery()
    )

    # Main query with left join to get child counts in single query
    threads_with_counts = (
        db.query(Thread, func.coalesce(child_count_subquery.c.child_count, 0).label("child_count"))
        .outerjoin(child_count_subquery, Thread.id == child_count_subquery.c.parent_thread_id)
        .filter(
            Thread.project_id == project_id,
            Thread.deleted_at.is_(None)
        )
        .order_by(Thread.updated_at.desc())
        .all()
    )

    return [
        ThreadResponse(
            id=t.id,
            project_id=t.project_id,
            title=t.title,
            created_at=t.created_at,
            updated_at=t.updated_at,
            parent_thread_id=t.parent_thread_id,
            context_text=t.context_text,
            child_count=child_count
        )
        for t, child_count in threads_with_counts
    ]


@router.get("/projects/{project_id}/threads/{thread_id}", response_model=ThreadDetail)
def get_thread(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get thread details including messages."""
    # Verify project ownership
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

    # Update project's last_thread_id when thread is accessed
    if project:
        project.last_thread_id = thread_id
        db.commit()

    return ThreadDetail(
        id=thread.id,
        project_id=thread.project_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        parent_thread_id=thread.parent_thread_id,
        context_text=thread.context_text,
        child_count=get_child_count(db, thread.id),
        messages=[
            MessageResponse(
                id=m.id,
                thread_id=m.thread_id,
                role=m.role,
                content=m.content,
                sources=m.sources,
                created_at=m.created_at
            )
            for m in thread.messages
        ]
    )


@router.patch("/projects/{project_id}/threads/{thread_id}", response_model=ThreadResponse)
def update_thread(
    project_id: str,
    thread_id: str,
    update: ThreadUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Update thread title."""
    # Verify project ownership
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

    if update.title is not None:
        thread.title = update.title
        thread.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        project_id=thread.project_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        parent_thread_id=thread.parent_thread_id,
        context_text=thread.context_text,
        child_count=get_child_count(db, thread.id)
    )


@router.delete("/projects/{project_id}/threads/{thread_id}")
def delete_thread(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Soft delete a thread."""
    # Verify project ownership
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

    # Soft delete
    thread.deleted_at = datetime.utcnow()
    db.commit()

    # If this was the project's last_thread_id, clear it or set to another thread
    if project and project.last_thread_id == thread_id:
        # Find another active thread
        other_thread = db.query(Thread).filter(
            Thread.project_id == project_id,
            Thread.deleted_at.is_(None)
        ).order_by(Thread.updated_at.desc()).first()
        project.last_thread_id = other_thread.id if other_thread else None
        db.commit()

    return {"status": "deleted", "id": thread_id}


@router.post("/projects/{project_id}/threads/{thread_id}/generate-title", response_model=ThreadResponse)
def auto_generate_title(
    project_id: str,
    thread_id: str,
    request: GenerateTitleRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Generate and set a thread title based on the first user message.

    Uses AI to create a short, contextual title from the message content.
    """
    # Verify project ownership
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

    # Generate title using AI
    new_title = generate_thread_title(request.message)

    # Update thread
    thread.title = new_title
    thread.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(thread)

    return ThreadResponse(
        id=thread.id,
        project_id=thread.project_id,
        title=thread.title,
        created_at=thread.created_at,
        updated_at=thread.updated_at,
        parent_thread_id=thread.parent_thread_id,
        context_text=thread.context_text,
        child_count=get_child_count(db, thread.id)
    )
