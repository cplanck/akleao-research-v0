"""Messages router for chat persistence."""

import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db, Project, Thread, Message
from api.schemas import MessageCreate, MessageResponse, SourceInfo

router = APIRouter(tags=["messages"])


@router.get("/projects/{project_id}/threads/{thread_id}/messages", response_model=list[MessageResponse])
def list_messages(
    project_id: str,
    thread_id: str,
    db: Session = Depends(get_db)
):
    """Get all messages for a thread."""
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

    result = []
    for msg in messages:
        sources = None
        if msg.sources:
            sources = [SourceInfo(**s) for s in json.loads(msg.sources)]
        result.append(MessageResponse(
            id=msg.id,
            thread_id=msg.thread_id,
            role=msg.role,
            content=msg.content,
            sources=sources,
            created_at=msg.created_at
        ))
    return result


@router.post("/projects/{project_id}/threads/{thread_id}/messages", response_model=MessageResponse)
def create_message(
    project_id: str,
    thread_id: str,
    message: MessageCreate,
    db: Session = Depends(get_db)
):
    """Create a new message in a thread."""
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
    db: Session = Depends(get_db)
):
    """Clear all messages in a thread."""
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
