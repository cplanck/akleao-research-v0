"""Notification API routes for job completion alerts."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel

from api.database import get_db, Project, Notification

router = APIRouter(tags=["notifications"])


# Response models
class NotificationResponse(BaseModel):
    id: str
    project_id: str
    thread_id: str | None = None
    job_id: str | None = None
    type: str
    title: str
    body: str | None = None
    read: bool
    created_at: datetime

    class Config:
        from_attributes = True


class UnreadCountResponse(BaseModel):
    count: int


def _notification_to_response(notification: Notification) -> NotificationResponse:
    """Convert a Notification to a NotificationResponse."""
    return NotificationResponse(
        id=notification.id,
        project_id=notification.project_id,
        thread_id=notification.thread_id,
        job_id=notification.job_id,
        type=notification.type.value,
        title=notification.title,
        body=notification.body,
        read=bool(notification.read),
        created_at=notification.created_at,
    )


@router.get("/projects/{project_id}/notifications", response_model=list[NotificationResponse])
def list_notifications(
    project_id: str,
    unread_only: bool = False,
    limit: int = 50,
    db: Session = Depends(get_db)
):
    """
    List notifications for a project.

    Args:
        project_id: The project to get notifications for
        unread_only: If True, only return unread notifications
        limit: Maximum number of notifications to return (default 50)
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Build query
    query = db.query(Notification).filter(Notification.project_id == project_id)

    if unread_only:
        query = query.filter(Notification.read == 0)

    # Order by newest first and limit
    notifications = query.order_by(Notification.created_at.desc()).limit(limit).all()

    return [_notification_to_response(n) for n in notifications]


@router.get("/projects/{project_id}/notifications/unread-count", response_model=UnreadCountResponse)
def get_unread_count(
    project_id: str,
    db: Session = Depends(get_db)
):
    """
    Get the count of unread notifications for a project.

    This is used to display the badge number on the notification bell.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    count = db.query(Notification).filter(
        Notification.project_id == project_id,
        Notification.read == 0
    ).count()

    return UnreadCountResponse(count=count)


@router.patch("/projects/{project_id}/notifications/{notification_id}", response_model=NotificationResponse)
def mark_notification_read(
    project_id: str,
    notification_id: str,
    db: Session = Depends(get_db)
):
    """
    Mark a single notification as read.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get notification
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.project_id == project_id
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    # Mark as read
    notification.read = 1
    notification.read_at = datetime.utcnow()
    db.commit()

    return _notification_to_response(notification)


@router.post("/projects/{project_id}/notifications/mark-all-read")
def mark_all_read(
    project_id: str,
    db: Session = Depends(get_db)
):
    """
    Mark all notifications for a project as read.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Update all unread notifications
    db.query(Notification).filter(
        Notification.project_id == project_id,
        Notification.read == 0
    ).update({
        Notification.read: 1,
        Notification.read_at: datetime.utcnow()
    })
    db.commit()

    return {"status": "ok", "message": "All notifications marked as read"}


@router.delete("/projects/{project_id}/notifications/{notification_id}")
def delete_notification(
    project_id: str,
    notification_id: str,
    db: Session = Depends(get_db)
):
    """
    Delete a notification.
    """
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get notification
    notification = db.query(Notification).filter(
        Notification.id == notification_id,
        Notification.project_id == project_id
    ).first()
    if not notification:
        raise HTTPException(status_code=404, detail="Notification not found")

    db.delete(notification)
    db.commit()

    return {"status": "ok", "message": "Notification deleted"}
