"""Messages router for chat persistence."""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db, Project, Thread, Message, User
from api.middleware.auth import get_current_user
from api.schemas import MessageCreate, MessageResponse, SourceInfo, ChildThreadInfo, ToolCallInfo

router = APIRouter(tags=["messages"])


@router.get("/projects/{project_id}/threads/{thread_id}/messages", response_model=list[MessageResponse])
def list_messages(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get all messages for a thread."""
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

    messages = (
        db.query(Message)
        .filter(Message.thread_id == thread_id)
        .order_by(Message.created_at)
        .all()
    )

    # Get all child threads spawned from messages in this thread
    message_ids = [m.id for m in messages]
    child_threads = db.query(Thread).filter(
        Thread.parent_message_id.in_(message_ids),
        Thread.deleted_at.is_(None)
    ).all()

    # Group child threads by parent_message_id
    children_by_message: dict[str, list[ChildThreadInfo]] = {}
    for child in child_threads:
        if child.parent_message_id not in children_by_message:
            children_by_message[child.parent_message_id] = []
        children_by_message[child.parent_message_id].append(ChildThreadInfo(
            id=child.id,
            title=child.title,
            context_text=child.context_text,
        ))

    result = []
    for msg in messages:
        sources = None
        if msg.sources:
            sources = [SourceInfo(**s) for s in json.loads(msg.sources)]

        tool_calls = None
        if msg.tool_calls:
            tool_calls = [ToolCallInfo(**tc) for tc in json.loads(msg.tool_calls)]

        result.append(MessageResponse(
            id=msg.id,
            thread_id=msg.thread_id,
            role=msg.role,
            content=msg.content,
            sources=sources,
            tool_calls=tool_calls,
            child_threads=children_by_message.get(msg.id),
            created_at=msg.created_at
        ))
    return result


@router.post("/projects/{project_id}/threads/{thread_id}/messages", response_model=MessageResponse)
def create_message(
    project_id: str,
    thread_id: str,
    message: MessageCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Create a new message in a thread."""
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

    sources_json = None
    if message.sources:
        sources_json = json.dumps([s.model_dump() for s in message.sources])

    db_message = Message(
        thread_id=thread_id,
        role=message.role,
        content=message.content,
        sources=sources_json
    )
    db.add(db_message)

    # Update thread's updated_at timestamp
    thread.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(db_message)

    return MessageResponse(
        id=db_message.id,
        thread_id=db_message.thread_id,
        role=db_message.role,
        content=db_message.content,
        sources=message.sources,
        created_at=db_message.created_at
    )


@router.delete("/projects/{project_id}/threads/{thread_id}/messages")
def clear_messages(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Clear all messages in a thread."""
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

    db.query(Message).filter(Message.thread_id == thread_id).delete()
    db.commit()
    return {"status": "cleared"}
