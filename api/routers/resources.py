"""Resource API routes."""

import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.database import get_db, Project, Resource, ResourceType, ResourceStatus, ProjectResource
from api.schemas import ResourceResponse, UrlResourceCreate, GitRepoResourceCreate, ResourceLinkRequest, GlobalResourceResponse
from api.utils.hashing import compute_content_hash, compute_url_hash, compute_git_hash
from rag import RAGPipeline

router = APIRouter(prefix="/projects/{project_id}/resources", tags=["resources"])

# Global resources router (no project_id prefix)
global_router = APIRouter(prefix="/resources", tags=["resources"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(exist_ok=True)

GIT_CLONE_DIR = Path("repos")
GIT_CLONE_DIR.mkdir(exist_ok=True)


def get_pipeline():
    """Get RAG pipeline instance."""
    pipeline = RAGPipeline()
    pipeline.initialize()
    return pipeline


def index_document(resource_id: str, file_path: str):
    """Background task to index a document.

    Now uses resource_id as Pinecone namespace for global resource sharing.
    """
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
            # Use resource_id as Pinecone namespace for global resource sharing
            result = pipeline.ingest(
                file_path,
                namespace=resource_id,  # Changed from project_id to resource_id
                resource_id=resource_id,
                generate_summary=True
            )

            # Calculate duration and record timing
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.pinecone_namespace = resource_id  # Track namespace (now resource-based)
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


def _link_resource_to_project(db: Session, resource: Resource, project_id: str):
    """Create ProjectResource link if it doesn't exist."""
    existing_link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource.id
    ).first()

    if not existing_link:
        link = ProjectResource(
            project_id=project_id,
            resource_id=resource.id,
            added_at=datetime.utcnow()
        )
        db.add(link)
        db.commit()


@router.post("", response_model=ResourceResponse)
async def add_resource(
    project_id: str,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    """Upload and index a document resource.

    If a resource with the same content hash already exists and is READY,
    we skip indexing and just link it to this project.
    """
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

    # Read file content for hashing
    file_content = await file.read()
    content_hash = compute_content_hash(content=file_content)

    # Check if resource with same hash already exists
    existing_resource = db.query(Resource).filter(
        Resource.content_hash == content_hash
    ).first()

    if existing_resource and existing_resource.status == ResourceStatus.READY:
        # Resource already exists and is indexed - just link to this project
        _link_resource_to_project(db, existing_resource, project_id)
        db.refresh(existing_resource)
        return existing_resource

    # Save uploaded file (need to reset file position after reading)
    project_upload_dir = UPLOAD_DIR / project_id
    project_upload_dir.mkdir(exist_ok=True)

    file_path = project_upload_dir / file.filename
    with open(file_path, "wb") as f:
        f.write(file_content)

    # Get file size
    file_size = len(file_content)

    # Create resource record (no project_id since resources are global now)
    resource = Resource(
        type=ResourceType.DOCUMENT,
        source=str(file_path),
        filename=file.filename,
        status=ResourceStatus.PENDING,
        file_size_bytes=file_size,
        content_hash=content_hash
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Create link to this project
    _link_resource_to_project(db, resource, project_id)

    # Index in background
    background_tasks.add_task(index_document, resource.id, str(file_path))

    db.refresh(resource)
    return resource


def index_url(resource_id: str, url: str):
    """Background task to index a URL resource.

    Now uses resource_id as Pinecone namespace for global resource sharing.
    """
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
            # Use resource_id as namespace for global resource sharing
            result = pipeline.ingest_url(
                url,
                namespace=resource_id,  # Changed from project_id to resource_id
                resource_id=resource_id,
                generate_summary=True
            )

            # Calculate duration and record timing
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.pinecone_namespace = resource_id  # Track namespace (now resource-based)
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


def index_git_repository(resource_id: str, repo_url: str, branch: str | None):
    """Background task to clone and index a git repository.

    Now uses resource_id as Pinecone namespace for global resource sharing.
    """
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

        # Create resource-specific clone directory (using resource_id)
        clone_dir = GIT_CLONE_DIR / resource_id
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

            # Ingest all documents - use resource_id as namespace
            ingest_result = pipeline.ingest_documents(
                documents,
                namespace=resource_id,  # Changed from project_id to resource_id
                resource_id=resource_id,
                generate_summary=True
            )

            # Update resource
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.commit_hash = commit_hash
            resource.pinecone_namespace = resource_id  # Track namespace (now resource-based)
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
    """Add and index a git repository.

    If a resource with the same git URL/branch already exists and is READY,
    we skip indexing and just link it to this project.
    """
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Compute hash based on URL and branch
    content_hash = compute_git_hash(request.url, request.branch)

    # Check if resource with same hash already exists
    existing_resource = db.query(Resource).filter(
        Resource.content_hash == content_hash
    ).first()

    if existing_resource and existing_resource.status == ResourceStatus.READY:
        # Resource already exists and is indexed - just link to this project
        _link_resource_to_project(db, existing_resource, project_id)
        db.refresh(existing_resource)
        return existing_resource

    # Extract repo name for filename
    repo_name = request.url.rstrip('/').rstrip('.git').split('/')[-1]

    # Create resource record (no project_id since resources are global now)
    resource = Resource(
        type=ResourceType.GIT_REPOSITORY,
        source=request.url,
        filename=repo_name,
        status=ResourceStatus.PENDING,
        content_hash=content_hash
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Create link to this project
    _link_resource_to_project(db, resource, project_id)

    background_tasks.add_task(
        index_git_repository,
        resource.id,
        request.url,
        request.branch
    )

    db.refresh(resource)
    return resource


@router.post("/url", response_model=ResourceResponse)
async def add_url_resource(
    project_id: str,
    request: UrlResourceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Add and index a URL resource (webpage or PDF).

    If a resource with the same URL already exists and is READY,
    we skip indexing and just link it to this project.
    """
    from urllib.parse import urlparse, unquote

    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Compute hash based on URL
    content_hash = compute_url_hash(request.url)

    # Check if resource with same hash already exists
    existing_resource = db.query(Resource).filter(
        Resource.content_hash == content_hash
    ).first()

    if existing_resource and existing_resource.status == ResourceStatus.READY:
        # Resource already exists and is indexed - just link to this project
        _link_resource_to_project(db, existing_resource, project_id)
        db.refresh(existing_resource)
        return existing_resource

    # Extract filename from URL path
    parsed = urlparse(request.url)
    path = unquote(parsed.path)
    filename = path.split("/")[-1] if path and "/" in path else None
    # If no extension or looks like a route, use domain as filename
    if not filename or "." not in filename:
        filename = parsed.netloc

    # Create resource record (no project_id since resources are global now)
    resource = Resource(
        type=ResourceType.WEBSITE,
        source=request.url,
        filename=filename,
        status=ResourceStatus.PENDING,
        content_hash=content_hash
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Create link to this project
    _link_resource_to_project(db, resource, project_id)

    # Index in background
    background_tasks.add_task(index_url, resource.id, request.url)

    db.refresh(resource)
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
    """Get a specific resource linked to a project."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if resource is linked to this project
    link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Resource not found in this project")

    return link.resource


@router.get("/{resource_id}/file")
def get_resource_file(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Download/view the resource file."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if resource is linked to this project
    link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Resource not found in this project")

    resource = link.resource
    if not resource.source or not os.path.exists(resource.source):
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=resource.source,
        filename=resource.filename,
        media_type="application/octet-stream"
    )


@router.delete("/{resource_id}")
def delete_resource(project_id: str, resource_id: str, db: Session = Depends(get_db)):
    """Remove a resource from a project.

    This unlinks the resource from the project. If the resource is not linked
    to any other projects, you can optionally fully delete it with ?permanent=true.
    """
    from fastapi import Query

    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if resource is linked to this project
    link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Resource not found in this project")

    resource = link.resource

    # Remove the link
    db.delete(link)
    db.commit()

    # Check if resource is now orphaned (no project links)
    remaining_links = db.query(ProjectResource).filter(
        ProjectResource.resource_id == resource_id
    ).count()

    if remaining_links == 0:
        # Resource is orphaned - for now keep it in library
        # Could add ?permanent=true query param to fully delete
        return {
            "status": "unlinked",
            "id": resource_id,
            "orphaned": True,
            "message": "Resource removed from project. It remains in the resource library."
        }

    return {"status": "unlinked", "id": resource_id, "orphaned": False}


@router.post("/{resource_id}/reindex", response_model=ResourceResponse)
async def reindex_resource(
    project_id: str,
    resource_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db)
):
    """Reindex a resource."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if resource is linked to this project
    link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Resource not found in this project")

    resource = link.resource

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
        background_tasks.add_task(index_document, resource.id, resource.source)
    elif resource.type == ResourceType.WEBSITE:
        # For websites, re-fetch from the URL
        background_tasks.add_task(index_url, resource.id, resource.source)
    elif resource.type == ResourceType.GIT_REPOSITORY:
        # For git repos, re-clone and re-index (use default branch on reindex)
        resource.commit_hash = None  # Clear old commit hash
        db.commit()
        db.refresh(resource)
        background_tasks.add_task(
            index_git_repository,
            resource.id,
            resource.source,  # URL
            None  # Use default branch on reindex
        )

    return resource


# ============================================================================
# Global Resource Endpoints (no project_id prefix)
# ============================================================================

@global_router.get("", response_model=list[GlobalResourceResponse])
def list_all_resources(
    skip: int = 0,
    limit: int = 100,
    status: ResourceStatus | None = None,
    db: Session = Depends(get_db)
):
    """List all global resources (resource library).

    Optional filtering by status.
    """
    query = db.query(Resource)

    if status:
        query = query.filter(Resource.status == status)

    resources = query.order_by(Resource.created_at.desc()).offset(skip).limit(limit).all()

    # Build response with project lists
    result = []
    for resource in resources:
        project_ids = [pr.project_id for pr in resource.project_resources]
        result.append(GlobalResourceResponse(
            id=resource.id,
            project_id=resource.project_id,
            type=resource.type,
            source=resource.source,
            filename=resource.filename,
            status=resource.status,
            error_message=resource.error_message,
            summary=resource.summary,
            created_at=resource.created_at,
            indexed_at=resource.indexed_at,
            indexing_duration_ms=resource.indexing_duration_ms,
            file_size_bytes=resource.file_size_bytes,
            commit_hash=resource.commit_hash,
            content_hash=resource.content_hash,
            project_count=resource.project_count,
            is_shared=resource.is_shared,
            projects=project_ids
        ))

    return result


@global_router.get("/{resource_id}", response_model=GlobalResourceResponse)
def get_global_resource(resource_id: str, db: Session = Depends(get_db)):
    """Get a specific resource from the global library."""
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    project_ids = [pr.project_id for pr in resource.project_resources]
    return GlobalResourceResponse(
        id=resource.id,
        project_id=resource.project_id,
        type=resource.type,
        source=resource.source,
        filename=resource.filename,
        status=resource.status,
        error_message=resource.error_message,
        summary=resource.summary,
        created_at=resource.created_at,
        indexed_at=resource.indexed_at,
        indexing_duration_ms=resource.indexing_duration_ms,
        file_size_bytes=resource.file_size_bytes,
        commit_hash=resource.commit_hash,
        content_hash=resource.content_hash,
        project_count=resource.project_count,
        is_shared=resource.is_shared,
        projects=project_ids
    )


@router.post("/link", response_model=ResourceResponse)
def link_resource_to_project(
    project_id: str,
    request: ResourceLinkRequest,
    db: Session = Depends(get_db)
):
    """Link an existing resource from the library to a project."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify resource exists
    resource = db.query(Resource).filter(Resource.id == request.resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Check if already linked
    existing_link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == request.resource_id
    ).first()

    if existing_link:
        # Already linked, just return the resource
        return resource

    # Create link
    link = ProjectResource(
        project_id=project_id,
        resource_id=request.resource_id,
        added_at=datetime.utcnow()
    )
    db.add(link)
    db.commit()
    db.refresh(resource)

    return resource


@global_router.get("/{resource_id}/chunks")
def get_resource_chunks(
    resource_id: str,
    limit: int = 500,
    db: Session = Depends(get_db)
):
    """Get the RAG chunks for a specific resource.

    Returns the chunks that were created during indexing, useful for debugging
    how documents are being parsed and split.
    """
    import os
    from dotenv import load_dotenv
    from rag.embeddings import Embedder
    from rag.vectorstore import VectorStore

    load_dotenv()

    # Verify resource exists
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    if resource.status != ResourceStatus.READY:
        raise HTTPException(
            status_code=400,
            detail=f"Resource is not indexed yet. Status: {resource.status.value}"
        )

    # Get the namespace (resource_id based)
    namespace = resource.pinecone_namespace or resource_id

    # Initialize vectorstore and fetch chunks
    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    embedder = Embedder(api_key=openai_key)
    vectorstore = VectorStore(
        api_key=pinecone_key,
        index_name=os.getenv("PINECONE_INDEX_NAME", "simage-rag"),
        dimension=embedder.dimensions
    )

    chunks = vectorstore.list_vectors(namespace=namespace, limit=limit * 10)  # Fetch more to account for filtering

    # Filter chunks to only include those belonging to this specific resource
    # This is necessary because multiple resources may share the same namespace
    # We filter by the 'source' field in metadata which matches resource.source in DB
    resource_source = resource.source
    filtered_chunks = [
        chunk for chunk in chunks
        if chunk.get("metadata", {}).get("source") == resource_source
    ]

    # Apply the limit after filtering
    filtered_chunks = filtered_chunks[:limit]

    return {
        "resource_id": resource_id,
        "namespace": namespace,
        "total_chunks": len(filtered_chunks),
        "chunks": filtered_chunks
    }


@global_router.delete("/{resource_id}")
def delete_global_resource(resource_id: str, db: Session = Depends(get_db)):
    """Permanently delete a resource from the library.

    This removes the resource completely, including all project links
    and the underlying file/Pinecone vectors.
    """
    resource = db.query(Resource).filter(Resource.id == resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Resource not found")

    # Delete uploaded file if exists
    if resource.source and os.path.exists(resource.source):
        os.remove(resource.source)

    # TODO: Delete vectors from Pinecone for this resource

    # Delete resource (cascade will delete ProjectResource links)
    db.delete(resource)
    db.commit()

    return {"status": "deleted", "id": resource_id}
