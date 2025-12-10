"""Messages router for chat persistence."""

import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db, Workspace, Message
from api.schemas import MessageCreate, MessageResponse, SourceInfo

router = APIRouter()


@router.get("", response_model=list[MessageResponse])
def list_messages(workspace_id: str, db: Session = Depends(get_db)):
    """Get all messages for a workspace."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    messages = (
        db.query(Message)
        .filter(Message.workspace_id == workspace_id)
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
            workspace_id=msg.workspace_id,
            role=msg.role,
            content=msg.content,
            sources=sources,
            created_at=msg.created_at
        ))
    return result


@router.post("", response_model=MessageResponse)
def create_message(
    workspace_id: str,
    message: MessageCreate,
    db: Session = Depends(get_db)
):
    """Create a new message in a workspace."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    sources_json = None
    if message.sources:
        sources_json = json.dumps([s.model_dump() for s in message.sources])

    db_message = Message(
        workspace_id=workspace_id,
        role=message.role,
        content=message.content,
        sources=sources_json
    )
    db.add(db_message)
    db.commit()
    db.refresh(db_message)

    return MessageResponse(
        id=db_message.id,
        workspace_id=db_message.workspace_id,
        role=db_message.role,
        content=db_message.content,
        sources=message.sources,
        created_at=db_message.created_at
    )


@router.delete("")
def clear_messages(workspace_id: str, db: Session = Depends(get_db)):
    """Clear all messages in a workspace."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    db.query(Message).filter(Message.workspace_id == workspace_id).delete()
    db.commit()
    return {"status": "cleared"}
