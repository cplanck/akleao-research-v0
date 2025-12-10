"""Workspace API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db, Workspace
from api.schemas import WorkspaceCreate, WorkspaceUpdate, WorkspaceResponse, WorkspaceDetail

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


@router.post("", response_model=WorkspaceResponse)
def create_workspace(workspace: WorkspaceCreate, db: Session = Depends(get_db)):
    """Create a new workspace."""
    db_workspace = Workspace(name=workspace.name)
    db.add(db_workspace)
    db.commit()
    db.refresh(db_workspace)
    return WorkspaceResponse(
        id=db_workspace.id,
        name=db_workspace.name,
        system_instructions=db_workspace.system_instructions,
        created_at=db_workspace.created_at,
        resource_count=0
    )


@router.get("", response_model=list[WorkspaceResponse])
def list_workspaces(db: Session = Depends(get_db)):
    """List all workspaces."""
    workspaces = db.query(Workspace).all()
    return [
        WorkspaceResponse(
            id=w.id,
            name=w.name,
            system_instructions=w.system_instructions,
            created_at=w.created_at,
            resource_count=len(w.resources)
        )
        for w in workspaces
    ]


@router.get("/{workspace_id}", response_model=WorkspaceDetail)
def get_workspace(workspace_id: str, db: Session = Depends(get_db)):
    """Get workspace details including resources."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")
    return WorkspaceDetail(
        id=workspace.id,
        name=workspace.name,
        system_instructions=workspace.system_instructions,
        created_at=workspace.created_at,
        resource_count=len(workspace.resources),
        resources=workspace.resources
    )


@router.patch("/{workspace_id}", response_model=WorkspaceResponse)
def update_workspace(
    workspace_id: str,
    update: WorkspaceUpdate,
    db: Session = Depends(get_db)
):
    """Update workspace settings (name, system instructions, etc.)."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Only update fields that were provided
    if update.name is not None:
        workspace.name = update.name
    if update.system_instructions is not None:
        workspace.system_instructions = update.system_instructions

    db.commit()
    db.refresh(workspace)

    return WorkspaceResponse(
        id=workspace.id,
        name=workspace.name,
        system_instructions=workspace.system_instructions,
        created_at=workspace.created_at,
        resource_count=len(workspace.resources)
    )


@router.delete("/{workspace_id}")
def delete_workspace(workspace_id: str, db: Session = Depends(get_db)):
    """Delete a workspace and all its resources."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # TODO: Also delete vectors from Pinecone namespace

    db.delete(workspace)
    db.commit()
    return {"status": "deleted", "id": workspace_id}
