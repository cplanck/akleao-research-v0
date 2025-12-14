"""Resource API routes."""

import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, BackgroundTasks
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from api.database import get_db, Project, Resource, ResourceType, ResourceStatus, ProjectResource, DataResourceMetadata, ImageResourceMetadata, User
from api.middleware.auth import get_current_user
from api.schemas import ResourceResponse, UrlResourceCreate, GitRepoResourceCreate, ResourceLinkRequest, GlobalResourceResponse, DataFileMetadata, ImageMetadata
from api.utils.hashing import compute_content_hash, compute_url_hash, compute_git_hash
from api.utils.file_types import detect_file_category, get_resource_type, is_allowed_extension, FileCategory, format_allowed_extensions
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


def resource_to_response(resource: Resource) -> ResourceResponse:
    """Convert a Resource ORM model to a ResourceResponse with metadata."""
    import json

    # Build data metadata if present
    data_metadata = None
    if resource.data_metadata:
        dm = resource.data_metadata[0] if isinstance(resource.data_metadata, list) and resource.data_metadata else resource.data_metadata
        if dm and hasattr(dm, 'row_count'):
            columns = None
            if dm.columns_json:
                try:
                    columns = json.loads(dm.columns_json)
                except:
                    pass
            data_metadata = DataFileMetadata(
                row_count=dm.row_count,
                column_count=dm.column_count,
                columns=columns,
                content_description=dm.content_description
            )

    # Build image metadata if present
    image_metadata = None
    if resource.image_metadata:
        im = resource.image_metadata[0] if isinstance(resource.image_metadata, list) and resource.image_metadata else resource.image_metadata
        if im and hasattr(im, 'width'):
            image_metadata = ImageMetadata(
                width=im.width,
                height=im.height,
                format=im.format,
                vision_description=im.vision_description
            )

    return ResourceResponse(
        id=resource.id,
        project_id=None,  # Resources are global now
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
        project_count=len(resource.project_resources) if resource.project_resources else 0,
        is_shared=len(resource.project_resources) > 1 if resource.project_resources else False,
        data_metadata=data_metadata,
        image_metadata=image_metadata
    )


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


def index_data_file(resource_id: str, file_path: str):
    """Background task to extract schema and generate description for data files (CSV, Excel, JSON).

    This doesn't use Pinecone - instead it extracts metadata and generates an LLM description
    that helps the agent route queries to the right data file.
    """
    from api.database import SessionLocal
    from datetime import datetime
    import time
    import json
    import pandas as pd
    import os
    from pathlib import Path
    from anthropic import Anthropic

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        start_time = time.time()
        try:
            # Load data based on extension
            ext = Path(file_path).suffix.lower()
            sheet_names = None

            if ext == ".csv":
                df = pd.read_csv(file_path, nrows=10000, on_bad_lines='skip')  # Limit rows, skip malformed lines
            elif ext == ".tsv":
                df = pd.read_csv(file_path, sep="\t", nrows=10000, on_bad_lines='skip')
            elif ext in (".xlsx", ".xls"):
                # For Excel, read first sheet but capture all sheet names
                xlsx = pd.ExcelFile(file_path)
                sheet_names = xlsx.sheet_names
                df = pd.read_excel(file_path, sheet_name=0, nrows=10000)
            elif ext == ".json":
                df = pd.read_json(file_path)
                if len(df) > 10000:
                    df = df.head(10000)
            elif ext == ".parquet":
                df = pd.read_parquet(file_path)
                if len(df) > 10000:
                    df = df.head(10000)
            else:
                raise ValueError(f"Unsupported data file type: {ext}")

            # Extract column information
            columns_info = []
            for col in df.columns:
                col_info = {
                    "name": str(col),
                    "dtype": str(df[col].dtype),
                    "null_count": int(df[col].isnull().sum()),
                }
                # Get sample values (non-null, up to 3)
                non_null = df[col].dropna()
                if len(non_null) > 0:
                    samples = non_null.head(3).tolist()
                    # Convert to strings for JSON serialization
                    col_info["sample_values"] = [str(s)[:100] for s in samples]
                columns_info.append(col_info)

            # Get sample rows (first 5)
            sample_rows = df.head(5).to_dict(orient="records")
            # Convert values to strings for JSON serialization
            for row in sample_rows:
                for k, v in row.items():
                    if pd.isna(v):
                        row[k] = None
                    elif not isinstance(v, (str, int, float, bool, type(None))):
                        row[k] = str(v)

            # Calculate numeric summary for numeric columns
            numeric_summary = {}
            for col in df.select_dtypes(include=['number']).columns:
                numeric_summary[str(col)] = {
                    "min": float(df[col].min()) if not pd.isna(df[col].min()) else None,
                    "max": float(df[col].max()) if not pd.isna(df[col].max()) else None,
                    "mean": float(df[col].mean()) if not pd.isna(df[col].mean()) else None,
                }

            # Generate LLM description using Haiku (crucial for routing!)
            content_description = _generate_data_description(
                filename=resource.filename,
                columns=columns_info,
                sample_rows=sample_rows[:3],
                row_count=len(df),
            )

            # Create metadata record
            metadata = DataResourceMetadata(
                resource_id=resource_id,
                columns_json=json.dumps(columns_info),
                row_count=len(df),
                column_count=len(df.columns),
                sheet_names_json=json.dumps(sheet_names) if sheet_names else None,
                sample_rows_json=json.dumps(sample_rows, default=str),
                content_description=content_description,
                numeric_summary_json=json.dumps(numeric_summary) if numeric_summary else None,
            )
            db.add(metadata)

            # Calculate duration and update resource
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.summary = content_description  # Use summary field for consistency
            db.commit()

        except Exception as e:
            import traceback
            resource.status = ResourceStatus.FAILED
            resource.error_message = f"{str(e)}\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()


def _generate_data_description(filename: str, columns: list, sample_rows: list, row_count: int) -> str:
    """Generate LLM description of data file content using Haiku."""
    import os
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    columns_str = ", ".join([f"{c['name']} ({c['dtype']})" for c in columns[:15]])
    if len(columns) > 15:
        columns_str += f"... and {len(columns) - 15} more columns"

    sample_str = "\n".join([str(row) for row in sample_rows[:2]])

    prompt = f"""Describe this data file in 2-3 sentences. Be specific about what kind of data it contains.

Filename: {filename}
Columns: {columns_str}
Row count: {row_count:,}
Sample rows:
{sample_str}

Focus on:
1. What kind of data this is (sales, inventory, users, logs, etc.)
2. Key entities/dimensions (customers, products, regions, dates, etc.)
3. What questions this data could answer

Start directly with "This is..." or "Contains..." - no preamble."""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=200,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text.strip()
    except Exception as e:
        # Fallback description if LLM fails
        return f"Data file with {row_count:,} rows and {len(columns)} columns: {columns_str[:200]}"


def index_image(resource_id: str, file_path: str):
    """Background task to extract metadata and generate vision description for images.

    Uses Claude's vision capability to generate a description that helps the agent
    route queries to the right image.
    """
    from api.database import SessionLocal
    from datetime import datetime
    import time
    import base64
    import os
    from pathlib import Path
    from PIL import Image
    from anthropic import Anthropic

    db = SessionLocal()
    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        resource.status = ResourceStatus.INDEXING
        db.commit()

        start_time = time.time()
        try:
            # Get image dimensions
            with Image.open(file_path) as img:
                width, height = img.size
                img_format = img.format or Path(file_path).suffix.upper().lstrip(".")

            # Generate vision description using Claude
            vision_description = _generate_vision_description(file_path, resource.filename)

            # Create metadata record
            metadata = ImageResourceMetadata(
                resource_id=resource_id,
                width=width,
                height=height,
                format=img_format,
                vision_description=vision_description,
            )
            db.add(metadata)

            # Calculate duration and update resource
            duration_ms = int((time.time() - start_time) * 1000)
            resource.status = ResourceStatus.READY
            resource.indexed_at = datetime.utcnow()
            resource.indexing_duration_ms = duration_ms
            resource.summary = vision_description  # Use summary field for consistency
            db.commit()

        except Exception as e:
            import traceback
            resource.status = ResourceStatus.FAILED
            resource.error_message = f"{str(e)}\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()


def _generate_vision_description(file_path: str, filename: str) -> str:
    """Generate description of image content using Claude's vision capability."""
    import os
    import base64
    from pathlib import Path
    from anthropic import Anthropic

    client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    # Read and encode image
    with open(file_path, "rb") as f:
        image_data = base64.standard_b64encode(f.read()).decode("utf-8")

    # Determine media type
    ext = Path(file_path).suffix.lower()
    media_types = {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/png")

    prompt = f"""Describe this image in 2-3 sentences. Be specific about what it shows.

Filename: {filename}

Focus on:
1. What type of image this is (screenshot, chart, diagram, photo, etc.)
2. Main content/subject
3. Key details that would help find this image later

If it's a chart, describe what data it shows.
If it's a diagram, describe its structure.
If it's a screenshot, describe the application/content.

Start directly with "This is..." or "Shows..." - no preamble."""

    try:
        response = client.messages.create(
            model="claude-3-haiku-20240307",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": image_data
                        }
                    },
                    {
                        "type": "text",
                        "text": prompt
                    }
                ]
            }]
        )
        return response.content[0].text.strip()
    except Exception as e:
        # Fallback description if vision fails
        return f"Image file: {filename}"


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Upload and process a resource file.

    Supports multiple file types:
    - Documents (PDF, DOCX, MD, TXT): RAG indexed for semantic search
    - Data files (CSV, Excel, JSON): Schema extraction for analysis
    - Images (PNG, JPG, etc.): Vision description for visual analysis

    If a resource with the same content hash already exists and is READY,
    we skip processing and just link it to this project.
    """
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Validate file type using new detection
    if not is_allowed_extension(file.filename):
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type. Allowed: {format_allowed_extensions()}"
        )

    # Detect file category and resource type
    file_category = detect_file_category(file.filename)
    resource_type = get_resource_type(file.filename, file_category)

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

    # Create resource record with detected type
    resource = Resource(
        type=resource_type,
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

    # Route to appropriate processing pipeline based on file category
    if file_category == FileCategory.RAG:
        # Traditional RAG indexing for documents
        background_tasks.add_task(index_document, resource.id, str(file_path))
    elif file_category == FileCategory.DATA:
        # Schema extraction and LLM description for data files
        background_tasks.add_task(index_data_file, resource.id, str(file_path))
    elif file_category == FileCategory.IMAGE:
        # Vision description for images
        background_tasks.add_task(index_image, resource.id, str(file_path))
    else:
        # Fallback to document indexing
        background_tasks.add_task(index_document, resource.id, str(file_path))

    db.refresh(resource)
    return resource_to_response(resource)


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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Add and index a git repository.

    If a resource with the same git URL/branch already exists and is READY,
    we skip indexing and just link it to this project.
    """
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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
    return resource_to_response(resource)


@router.post("/url", response_model=ResourceResponse)
async def add_url_resource(
    project_id: str,
    request: UrlResourceCreate,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Add and index a URL resource (webpage or PDF).

    If a resource with the same URL already exists and is READY,
    we skip indexing and just link it to this project.
    """
    from urllib.parse import urlparse, unquote

    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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
    return resource_to_response(resource)


@router.get("", response_model=list[ResourceResponse])
def list_resources(
    project_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """List all resources in a project."""
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    return [resource_to_response(r) for r in project.resources]


@router.get("/{resource_id}", response_model=ResourceResponse)
def get_resource(
    project_id: str,
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Get a specific resource linked to a project."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Check if resource is linked to this project
    link = db.query(ProjectResource).filter(
        ProjectResource.project_id == project_id,
        ProjectResource.resource_id == resource_id
    ).first()

    if not link:
        raise HTTPException(status_code=404, detail="Resource not found in this project")

    return resource_to_response(link.resource)


@router.get("/{resource_id}/file")
def get_resource_file(
    project_id: str,
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Download/view the resource file."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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
def delete_resource(
    project_id: str,
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Remove a resource from a project.

    This unlinks the resource from the project. If the resource is not linked
    to any other projects, you can optionally fully delete it with ?permanent=true.
    """
    from fastapi import Query

    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Reindex a resource."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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

    return resource_to_response(resource)


# ============================================================================
# Global Resource Endpoints (no project_id prefix)
# ============================================================================

@global_router.get("", response_model=list[GlobalResourceResponse])
def list_all_resources(
    skip: int = 0,
    limit: int = 100,
    status: ResourceStatus | None = None,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
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
def get_global_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
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
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Link an existing resource from the library to a project."""
    # Verify project exists and belongs to user
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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
        return resource_to_response(resource)

    # Create link
    link = ProjectResource(
        project_id=project_id,
        resource_id=request.resource_id,
        added_at=datetime.utcnow()
    )
    db.add(link)
    db.commit()
    db.refresh(resource)

    return resource_to_response(resource)


@global_router.get("/{resource_id}/chunks")
def get_resource_chunks(
    resource_id: str,
    limit: int = 500,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
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
def delete_global_resource(
    resource_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
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
