"""Resource API routes."""

import os
import shutil
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.database import get_db, Workspace, Resource, ResourceType, ResourceStatus
from api.schemas import ResourceResponse, UrlResourceCreate
from rag import RAGPipeline

router = APIRouter(prefix="/workspaces/{workspace_id}/resources", tags=["resources"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)


def get_pipeline():
    """Get RAG pipeline instance."""
    pipeline = RAGPipeline()
    pipeline.initialize()
    return pipeline


def index_document(resource_id: str, file_path: str, workspace_id: str):
    """Background task to index a document."""
    from api.database import SessionLocal

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        try:
            pipeline = get_pipeline()
            # Use workspace_id as Pinecone namespace, pass resource_id for source linking
            pipeline.ingest(file_path, namespace=workspace_id, resource_id=resource_id)

            resource.status = ResourceStatus.READY
            db.commit()
        except Exception as e:
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            db.commit()
    finally:
        db.close()


@router.post("", response_model=ResourceResponse)
async def add_resource(
    workspace_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and index a document resource."""
    # Verify workspace exists
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Validate file type
    allowed_extensions = {".pdf", ".docx", ".md", ".txt", ".markdown"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Save uploaded file
    workspace_upload_dir = UPLOAD_DIR / workspace_id
    workspace_upload_dir.mkdir(exist_ok=True)

    file_path = workspace_upload_dir / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Create resource record
    resource = Resource(
        workspace_id=workspace_id,
        type=ResourceType.DOCUMENT,
        source=str(file_path),
        filename=file.filename,
        status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Index in background
    background_tasks.add_task(index_document, resource.id, str(file_path), workspace_id)

    return resource


def index_url(resource_id: str, url: str, workspace_id: str):
    """Background task to index a URL resource."""
    from api.database import SessionLocal
    import traceback

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        try:
            pipeline = get_pipeline()
            pipeline.ingest_url(url, namespace=workspace_id, resource_id=resource_id)

            resource.status = ResourceStatus.READY
            db.commit()
        except Exception as e:
            print(f"Error indexing URL {url}: {e}")
            traceback.print_exc()
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            db.commit()
    finally:
        db.close()


@router.post("/url", response_model=ResourceResponse)
async def add_url_resource(
    workspace_id: str,
    request: UrlResourceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Add and index a URL resource (webpage or PDF)."""
    from urllib.parse import urlparse, unquote

    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    # Extract filename from URL path
    parsed = urlparse(request.url)
    path = unquote(parsed.path)
    filename = path.split("/")[-1] if path and "/" in path else None
    # If no extension or looks like a route, use domain as filename
    if not filename or "." not in filename:
        filename = parsed.netloc

    # Create resource record
    resource = Resource(
        workspace_id=workspace_id,
        type=ResourceType.WEBSITE,
        source=request.url,
        filename=filename,
        status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Index in background
    background_tasks.add_task(index_url, resource.id, request.url, workspace_id)

    return resource


@router.get("", response_model=list[ResourceResponse])
def list_resources(workspace_id: str, db: Session = Depends(get_db)):
    """List all resources in a workspace."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    return workspace.resources


@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(workspace_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Get a specific resource."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.workspace_id == workspace_id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/{resource_id}/file")
def get_resource_file(workspace_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Download/view the resource file."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.workspace_id == workspace_id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    if not resource.source or not os.path.exists(resource.source):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=resource.source,
        filename=resource.filename,
        media_type="application/octet-stream"
    )


@router.delete("/{resource_id}")
def delete_resource(workspace_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Delete a resource."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.workspace_id == workspace_id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Delete uploaded file
    if resource.source and os.path.exists(resource.source):
        os.remove(resource.source)

    # TODO: Delete vectors from Pinecone for this resource

    db.delete(resource)
    db.commit()
    return {"status": "deleted", "id": resource_id}
