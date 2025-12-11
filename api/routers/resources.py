"""Resource API routes."""

import os
import shutil
import subprocess
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.database import get_db, Project, Resource, ResourceType, ResourceStatus
from api.schemas import ResourceResponse, UrlResourceCreate, GitRepoResourceCreate
from rag import RAGPipeline

router = APIRouter(prefix="/projects/{project_id}/resources", tags=["resources"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

GIT_CLONE_DIR = Path("repos")
GIT_CLONE_DIR.mkdir(exist_ok=True)


def get_pipeline():
    """Get RAG pipeline instance."""
    pipeline = RAGPipeline()
    pipeline.initialize()
    return pipeline


def index_document(resource_id: str, file_path: str, project_id: str):
    """Background task to index a document."""
    from api.database import SessionLocal
    from datetime import datetime
    import time

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        start_time = time.time()
        try:
            pipeline = get_pipeline()
            # Use project_id as Pinecone namespace, pass resource_id for source linking
            # Enable summary generation
            result = pipeline.ingest(
                file_path,
                namespace=project_id,
                resource_id=resource_id,
                generate_summary=True
            )

            # Calculate duration and record timing
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.pinecone_namespace = project_id  # Track which namespace vectors are stored in
            # Save the generated summary
            if result.get("summary"):
                resource.summary = result["summary"]
            db.commit()
        except Exception as e:
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            db.commit()
    finally:
        db.close()


@router.post("", response_model=ResourceResponse)
async def add_resource(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and index a document resource."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate file type
    allowed_extensions = {".pdf", ".docx", ".md", ".txt", ".markdown"}
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in allowed_extensions:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {', '.join(allowed_extensions)}"
        )

    # Save uploaded file
    project_upload_dir = UPLOAD_DIR / project_id
    project_upload_dir.mkdir(exist_ok=True)

    file_path = project_upload_dir / file.filename
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Get file size
    file_size = file_path.stat().st_size

    # Create resource record
    resource = Resource(
        project_id=project_id,
        type=ResourceType.DOCUMENT,
        source=str(file_path),
        filename=file.filename,
        status=ResourceStatus.PENDING,
        file_size_bytes=file_size
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Index in background
    background_tasks.add_task(index_document, resource.id, str(file_path), project_id)

    return resource


def index_url(resource_id: str, url: str, project_id: str):
    """Background task to index a URL resource."""
    from api.database import SessionLocal
    from datetime import datetime
    import traceback
    import time

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        start_time = time.time()
        try:
            pipeline = get_pipeline()
            # Enable summary generation
            result = pipeline.ingest_url(
                url,
                namespace=project_id,
                resource_id=resource_id,
                generate_summary=True
            )

            # Calculate duration and record timing
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.pinecone_namespace = project_id  # Track which namespace vectors are stored in
            # Save the generated summary
            if result.get("summary"):
                resource.summary = result["summary"]
            db.commit()
        except Exception as e:
            print(f"Error indexing URL {url}: {e}")
            traceback.print_exc()
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            db.commit()
    finally:
        db.close()


def index_git_repository(resource_id: str, repo_url: str, branch: str | None, project_id: str):
    """Background task to clone and index a git repository."""
    from api.database import SessionLocal
    from datetime import datetime
    import time
    import traceback

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        start_time = time.time()

        # Create project-specific clone directory
        clone_dir = GIT_CLONE_DIR / project_id / resource_id
        clone_dir.parent.mkdir(parents=True, exist_ok=True)

        try:
            # Clone the repository (shallow clone for speed)
            clone_cmd = ["git", "clone", "--depth", "1"]
            if branch:
                clone_cmd.extend(["--branch", branch])
            clone_cmd.extend([repo_url, str(clone_dir)])

            print(f"[Git] Cloning repository: {repo_url}")
            result = subprocess.run(
                clone_cmd,
                check=True,
                capture_output=True,
                timeout=300  # 5 minute timeout for clone
            )

            # Get commit hash
            hash_result = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=clone_dir,
                capture_output=True,
                text=True
            )
            commit_hash = hash_result.stdout.strip()[:12]  # Short hash
            print(f"[Git] Cloned at commit: {commit_hash}")

            # Load documents from repo with GitHub URL info
            pipeline = get_pipeline()
            loader = pipeline.loader
            documents = loader.load_git_repository(
                str(clone_dir),
                repo_url=repo_url,
                commit_hash=commit_hash
            )
            print(f"[Git] Found {len(documents)} indexable files")

            if not documents:
                resource.status = ResourceStatus.FAILED
                resource.error_message = "No indexable files found in repository"
                db.commit()
                return

            # Ingest all documents
            ingest_result = pipeline.ingest_documents(
                documents,
                namespace=project_id,
                resource_id=resource_id,
                generate_summary=True
            )

            # Update resource
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.commit_hash = commit_hash
            resource.pinecone_namespace = project_id  # Track which namespace vectors are stored in
            if ingest_result.get("summary"):
                resource.summary = ingest_result["summary"]
            db.commit()
            print(f"[Git] Indexing complete: {ingest_result['documents']} files, {ingest_result['chunks']} chunks")

        except subprocess.CalledProcessError as e:
            error_msg = e.stderr.decode() if e.stderr else str(e)
            print(f"[Git] Clone failed: {error_msg}")
            resource.status = ResourceStatus.FAILED
            resource.error_message = f"Git clone failed: {error_msg}"
            db.commit()
        except subprocess.TimeoutExpired:
            print(f"[Git] Clone timed out for {repo_url}")
            resource.status = ResourceStatus.FAILED
            resource.error_message = "Git clone timed out (5 minute limit)"
            db.commit()
        except Exception as e:
            print(f"[Git] Error indexing repository: {e}")
            traceback.print_exc()
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            db.commit()
        finally:
            # Clean up cloned repo to save disk space
            if clone_dir.exists():
                shutil.rmtree(clone_dir, ignore_errors=True)
                print(f"[Git] Cleaned up clone directory")
    finally:
        db.close()


@router.post("/git", response_model=ResourceResponse)
async def add_git_resource(
    project_id: str,
    request: GitRepoResourceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Add and index a git repository."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Extract repo name for filename
    repo_name = request.url.rstrip('/').rstrip('.git').split('/')[-1]

    resource = Resource(
        project_id=project_id,
        type=ResourceType.GIT_REPOSITORY,
        source=request.url,
        filename=repo_name,
        status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    background_tasks.add_task(
        index_git_repository,
        resource.id,
        request.url,
        request.branch,
        project_id
    )

    return resource


@router.post("/url", response_model=ResourceResponse)
async def add_url_resource(
    project_id: str,
    request: UrlResourceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Add and index a URL resource (webpage or PDF)."""
    from urllib.parse import urlparse, unquote

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Extract filename from URL path
    parsed = urlparse(request.url)
    path = unquote(parsed.path)
    filename = path.split("/")[-1] if path and "/" in path else None
    # If no extension or looks like a route, use domain as filename
    if not filename or "." not in filename:
        filename = parsed.netloc

    # Create resource record
    resource = Resource(
        project_id=project_id,
        type=ResourceType.WEBSITE,
        source=request.url,
        filename=filename,
        status=ResourceStatus.PENDING
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Index in background
    background_tasks.add_task(index_url, resource.id, request.url, project_id)

    return resource


@router.get("", response_model=list[ResourceResponse])
def list_resources(project_id: str, db: Session = Depends(get_db)):
    """List all resources in a project."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return project.resources


@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Get a specific resource."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.project_id == project_id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")
    return resource


@router.get("/{resource_id}/file")
def get_resource_file(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Download/view the resource file."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.project_id == project_id
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
def delete_resource(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Delete a resource."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.project_id == project_id
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


@router.post("/{resource_id}/reindex", response_model=ResourceResponse)
async def reindex_resource(
    project_id: str,
    resource_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Reindex a resource."""
    resource = db.query(Resource).filter(
        Resource.id == resource_id,
        Resource.project_id == project_id
    ).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Reset status and clear previous indexing stats
    resource.status = ResourceStatus.PENDING
    resource.indexed_at = None
    resource.indexing_duration_ms = None
    resource.error_message = None
    resource.summary = None
    db.commit()
    db.refresh(resource)

    # Queue reindexing based on resource type
    if resource.type == ResourceType.DOCUMENT:
        # For documents, use the stored file path
        if not resource.source or not os.path.exists(resource.source):
            resource.status = ResourceStatus.FAILED
            resource.error_message = "Source file not found"
            db.commit()
            db.refresh(resource)
            raise HTTPException(status_code=400, detail="Source file not found for reindexing")
        background_tasks.add_task(index_document, resource.id, resource.source, project_id)
    elif resource.type == ResourceType.WEBSITE:
        # For websites, re-fetch from the URL
        background_tasks.add_task(index_url, resource.id, resource.source, project_id)
    elif resource.type == ResourceType.GIT_REPOSITORY:
        # For git repos, re-clone and re-index (use default branch on reindex)
        resource.commit_hash = None  # Clear old commit hash
        db.commit()
        db.refresh(resource)
        background_tasks.add_task(
            index_git_repository,
            resource.id,
            resource.source,  # URL
            None,  # Use default branch on reindex
            project_id
        )

    return resource
