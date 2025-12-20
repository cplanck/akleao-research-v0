"""Test Resources API routes for the Test Suite.

These endpoints manage test resources - problematic files/URLs kept for regression testing.
Each test resource can be re-processed on demand to measure system improvement.
"""

import os
import json
import hashlib
import time
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, BackgroundTasks
from sqlalchemy.orm import Session

from api.database import get_db, TestResource, TestRun, TestRunStatus, ResourceType
from api.schemas import (
    TestResourceCreate,
    TestResourceUrlCreate,
    TestResourceGitCreate,
    TestResourceResponse,
    TestResourceWithRunsResponse,
    TestRunResponse,
    RunAllResponse,
)
from api.storage import get_storage

router = APIRouter(prefix="/test-resources", tags=["test-resources"])

# Test resources storage directory (separate from production)
TEST_UPLOAD_DIR = Path("test_uploads")
TEST_UPLOAD_DIR.mkdir(exist_ok=True)


def compute_content_hash(file_content: bytes) -> str:
    """Compute SHA256 hash of file content."""
    return hashlib.sha256(file_content).hexdigest()


def test_run_to_response(run: TestRun) -> TestRunResponse:
    """Convert TestRun ORM model to response schema."""
    raw_metadata = None
    if run.raw_metadata:
        try:
            raw_metadata = json.loads(run.raw_metadata)
        except:
            pass

    return TestRunResponse(
        id=run.id,
        test_resource_id=run.test_resource_id,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status=run.status,
        error_message=run.error_message,
        extraction_duration_ms=run.extraction_duration_ms,
        indexing_duration_ms=run.indexing_duration_ms,
        total_duration_ms=run.total_duration_ms,
        chunk_count=run.chunk_count,
        summary=run.summary,
        raw_metadata=raw_metadata,
    )


def test_resource_to_response(resource: TestResource, include_runs: bool = False) -> TestResourceResponse | TestResourceWithRunsResponse:
    """Convert TestResource ORM model to response schema."""
    # Get most recent run
    last_run = None
    if resource.runs:
        sorted_runs = sorted(resource.runs, key=lambda r: r.started_at, reverse=True)
        if sorted_runs:
            last_run = test_run_to_response(sorted_runs[0])

    base_data = {
        "id": resource.id,
        "name": resource.name,
        "description": resource.description,
        "type": resource.type,
        "filename": resource.filename,
        "storage_path": resource.storage_path,
        "file_size_bytes": resource.file_size_bytes,
        "content_hash": resource.content_hash,
        "created_at": resource.created_at,
        "source_url": resource.source_url,
        "git_branch": resource.git_branch,
        "last_run": last_run,
    }

    if include_runs:
        runs = [test_run_to_response(r) for r in sorted(resource.runs, key=lambda r: r.started_at, reverse=True)]
        return TestResourceWithRunsResponse(**base_data, runs=runs)
    return TestResourceResponse(**base_data)


# CRUD Endpoints

@router.get("", response_model=list[TestResourceResponse])
def list_test_resources(db: Session = Depends(get_db)):
    """List all test resources."""
    resources = db.query(TestResource).order_by(TestResource.created_at.desc()).all()
    return [test_resource_to_response(r) for r in resources]


@router.post("", response_model=TestResourceResponse)
async def create_test_resource(
    name: str = Form(...),
    description: str = Form(None),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """Upload a new test resource file."""
    from api.utils.file_types import get_resource_type, is_allowed_extension

    # Validate file extension
    filename = file.filename or "unknown"
    if not is_allowed_extension(filename):
        raise HTTPException(status_code=400, detail=f"File type not allowed: {filename}")

    # Determine resource type from file
    resource_type = get_resource_type(filename)

    # Read file content
    content = await file.read()
    content_hash = compute_content_hash(content)
    file_size = len(content)

    # Create test resource record first to get ID
    test_resource = TestResource(
        name=name,
        description=description,
        type=resource_type,
        filename=filename,
        storage_path="",  # Will update after saving
        file_size_bytes=file_size,
        content_hash=content_hash,
    )
    db.add(test_resource)
    db.commit()
    db.refresh(test_resource)

    # Save file to test storage using the storage API
    # The storage.save() returns the full path
    storage = get_storage()
    # Use "test_" prefix on project_id to keep test files separate
    storage_path = storage.save(f"test_{test_resource.id}", filename, content)

    # Update storage path
    test_resource.storage_path = storage_path
    db.commit()
    db.refresh(test_resource)

    return test_resource_to_response(test_resource)


@router.post("/url", response_model=TestResourceResponse)
def create_test_resource_from_url(
    data: TestResourceUrlCreate,
    db: Session = Depends(get_db),
):
    """Create a test resource from a URL (website)."""
    from api.utils.hashing import compute_url_hash

    # Compute URL hash for deduplication
    content_hash = compute_url_hash(data.url)

    test_resource = TestResource(
        name=data.name,
        description=data.description,
        type=ResourceType.WEBSITE,
        source_url=data.url,
        storage_path=f"url:{data.url}",  # Virtual path for URLs
        content_hash=content_hash,
    )
    db.add(test_resource)
    db.commit()
    db.refresh(test_resource)

    return test_resource_to_response(test_resource)


@router.post("/git", response_model=TestResourceResponse)
def create_test_resource_from_git(
    data: TestResourceGitCreate,
    db: Session = Depends(get_db),
):
    """Create a test resource from a git repository."""
    from api.utils.hashing import compute_git_hash

    # Compute git hash for deduplication
    content_hash = compute_git_hash(data.url, data.branch)

    test_resource = TestResource(
        name=data.name,
        description=data.description,
        type=ResourceType.GIT_REPOSITORY,
        source_url=data.url,
        git_branch=data.branch,
        storage_path=f"git:{data.url}",  # Virtual path for git repos
        content_hash=content_hash,
    )
    db.add(test_resource)
    db.commit()
    db.refresh(test_resource)

    return test_resource_to_response(test_resource)


@router.get("/{test_resource_id}", response_model=TestResourceWithRunsResponse)
def get_test_resource(test_resource_id: str, db: Session = Depends(get_db)):
    """Get a single test resource with all its runs."""
    resource = db.query(TestResource).filter(TestResource.id == test_resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Test resource not found")
    return test_resource_to_response(resource, include_runs=True)


@router.delete("/{test_resource_id}")
def delete_test_resource(test_resource_id: str, db: Session = Depends(get_db)):
    """Delete a test resource and all its runs."""
    resource = db.query(TestResource).filter(TestResource.id == test_resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Test resource not found")

    # Delete file from storage if it exists
    if resource.storage_path and not resource.storage_path.startswith(("url:", "git:")):
        try:
            storage = get_storage()
            storage.delete(resource.storage_path)
        except Exception as e:
            print(f"[TestResources] Failed to delete file {resource.storage_path}: {e}")

    db.delete(resource)
    db.commit()
    return {"status": "deleted", "id": test_resource_id}


# Run Endpoints

@router.get("/{test_resource_id}/runs", response_model=list[TestRunResponse])
def get_test_resource_runs(test_resource_id: str, db: Session = Depends(get_db)):
    """Get run history for a test resource."""
    resource = db.query(TestResource).filter(TestResource.id == test_resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Test resource not found")

    runs = db.query(TestRun).filter(
        TestRun.test_resource_id == test_resource_id
    ).order_by(TestRun.started_at.desc()).all()

    return [test_run_to_response(r) for r in runs]


@router.post("/{test_resource_id}/run", response_model=TestRunResponse)
def run_test_resource(
    test_resource_id: str,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger a test run for a single resource."""
    resource = db.query(TestResource).filter(TestResource.id == test_resource_id).first()
    if not resource:
        raise HTTPException(status_code=404, detail="Test resource not found")

    # Create a new test run
    test_run = TestRun(
        test_resource_id=test_resource_id,
        status=TestRunStatus.PENDING,
    )
    db.add(test_run)
    db.commit()
    db.refresh(test_run)

    # Queue background processing
    background_tasks.add_task(process_test_run, test_run.id)

    return test_run_to_response(test_run)


@router.post("/run-all", response_model=RunAllResponse)
def run_all_test_resources(
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger test runs for all resources."""
    resources = db.query(TestResource).all()
    if not resources:
        return RunAllResponse(message="No test resources to run", run_ids=[])

    run_ids = []
    for resource in resources:
        test_run = TestRun(
            test_resource_id=resource.id,
            status=TestRunStatus.PENDING,
        )
        db.add(test_run)
        db.commit()
        db.refresh(test_run)
        run_ids.append(test_run.id)

        # Queue background processing
        background_tasks.add_task(process_test_run, test_run.id)

    return RunAllResponse(
        message=f"Started {len(run_ids)} test runs",
        run_ids=run_ids,
    )


@router.get("/runs/{run_id}", response_model=TestRunResponse)
def get_test_run(run_id: str, db: Session = Depends(get_db)):
    """Get details of a single test run."""
    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")
    return test_run_to_response(run)


# Query endpoint for testing retrieval
from pydantic import BaseModel

class TestQueryRequest(BaseModel):
    question: str
    top_k: int = 5
    system_prompt: str | None = None

class TestQuerySource(BaseModel):
    content: str
    source: str
    score: float

class TestQueryResponse(BaseModel):
    answer: str
    sources: list[TestQuerySource]
    namespace: str

@router.post("/runs/{run_id}/query", response_model=TestQueryResponse)
def query_test_run(run_id: str, request: TestQueryRequest, db: Session = Depends(get_db)):
    """Query against a test run's indexed content.

    This allows testing retrieval quality by asking questions
    against the chunks created during a test run.
    """
    from rag import RAGPipeline

    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    if run.status != TestRunStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Test run is not successful (status: {run.status})")

    # Get namespace from raw_metadata
    namespace = None
    if run.raw_metadata:
        try:
            metadata = json.loads(run.raw_metadata)
            namespace = metadata.get("namespace")
        except:
            pass

    if not namespace:
        raise HTTPException(status_code=400, detail="Test run has no namespace - cannot query")

    # Query the RAG pipeline
    pipeline = RAGPipeline()
    pipeline.initialize()

    result = pipeline.query(
        question=request.question,
        top_k=request.top_k,
        namespace=namespace,
        return_sources=True,
        system_prompt=request.system_prompt
    )

    return TestQueryResponse(
        answer=result["answer"],
        sources=[
            TestQuerySource(
                content=s["content"],
                source=s["source"],
                score=s["score"]
            )
            for s in result["sources"]
        ],
        namespace=namespace
    )


class TestRunChunk(BaseModel):
    id: str
    content: str
    source: str
    metadata: dict

class TestRunChunksResponse(BaseModel):
    chunks: list[TestRunChunk]
    namespace: str
    total: int

@router.get("/runs/{run_id}/chunks", response_model=TestRunChunksResponse)
def get_test_run_chunks(run_id: str, limit: int = 100, db: Session = Depends(get_db)):
    """Get all chunks indexed during a test run."""
    from rag import RAGPipeline

    run = db.query(TestRun).filter(TestRun.id == run_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Test run not found")

    if run.status != TestRunStatus.SUCCESS:
        raise HTTPException(status_code=400, detail=f"Test run is not successful (status: {run.status})")

    # Get namespace from raw_metadata
    namespace = None
    if run.raw_metadata:
        try:
            metadata = json.loads(run.raw_metadata)
            namespace = metadata.get("namespace")
        except:
            pass

    if not namespace:
        raise HTTPException(status_code=400, detail="Test run has no namespace")

    # Fetch chunks from Pinecone
    pipeline = RAGPipeline()
    pipeline.initialize()

    vectors = pipeline.vectorstore.list_vectors(namespace=namespace, limit=limit)

    chunks = [
        TestRunChunk(
            id=v["id"],
            content=v.get("content", ""),
            source=v.get("source", ""),
            metadata={k: v for k, v in v.items() if k not in ["id", "content", "source"]}
        )
        for v in vectors
    ]

    return TestRunChunksResponse(
        chunks=chunks,
        namespace=namespace,
        total=len(chunks)
    )


# Background Processing

def process_test_run(run_id: str):
    """Process a test run through the RAG pipeline.

    This runs in a background task and:
    1. Downloads the test resource file
    2. Processes it through the RAG pipeline with a temporary namespace
    3. Captures metrics and results
    4. Cleans up the temporary namespace
    """
    from api.database import SessionLocal
    from api.storage import get_storage
    from rag import RAGPipeline
    import tempfile

    db = SessionLocal()
    try:
        run = db.query(TestRun).filter(TestRun.id == run_id).first()
        if not run:
            return

        resource = run.test_resource
        if not resource:
            run.status = TestRunStatus.FAILED
            run.error_message = "Test resource not found"
            run.completed_at = datetime.utcnow()
            db.commit()
            return

        # Mark as processing
        run.status = TestRunStatus.PROCESSING
        db.commit()

        start_time = time.time()
        extraction_start = start_time
        local_path = None
        temp_namespace = f"test_{run_id}"

        try:
            # Handle different resource types
            if resource.type == ResourceType.WEBSITE:
                # Process website URL directly through pipeline
                extraction_end = time.time()
                run.extraction_duration_ms = int((extraction_end - extraction_start) * 1000)
                db.commit()

                indexing_start = time.time()
                pipeline = RAGPipeline()
                pipeline.initialize()

                result = pipeline.ingest_url(
                    resource.source_url,
                    namespace=temp_namespace,
                    resource_id=run_id,
                    generate_summary=True,
                )

                indexing_end = time.time()
                run.indexing_duration_ms = int((indexing_end - indexing_start) * 1000)

            elif resource.type == ResourceType.GIT_REPOSITORY:
                # Process git repository
                from rag.ingest import GitLoader

                extraction_end = time.time()
                run.extraction_duration_ms = int((extraction_end - extraction_start) * 1000)
                db.commit()

                indexing_start = time.time()
                pipeline = RAGPipeline()
                pipeline.initialize()

                # Clone and load git repo
                git_loader = GitLoader()
                documents = git_loader.load(resource.source_url, branch=resource.git_branch)

                # Ingest the documents
                result = pipeline.ingest_documents(
                    documents,
                    namespace=temp_namespace,
                    resource_id=run_id,
                    generate_summary=True,
                )

                indexing_end = time.time()
                run.indexing_duration_ms = int((indexing_end - indexing_start) * 1000)

            else:
                # Process file-based resources (documents, data files, images)
                storage = get_storage()
                file_content = storage.read(resource.storage_path)

                # Create temp file
                ext = Path(resource.storage_path).suffix
                with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
                    tmp.write(file_content)
                    local_path = tmp.name

                extraction_end = time.time()
                run.extraction_duration_ms = int((extraction_end - extraction_start) * 1000)
                db.commit()

                # Process through RAG pipeline
                indexing_start = time.time()
                pipeline = RAGPipeline()
                pipeline.initialize()

                result = pipeline.ingest(
                    local_path,
                    namespace=temp_namespace,
                    resource_id=run_id,  # Use run_id as resource_id for test
                    generate_summary=True,
                )

                indexing_end = time.time()
                run.indexing_duration_ms = int((indexing_end - indexing_start) * 1000)

            # Update run with results
            end_time = time.time()
            run.total_duration_ms = int((end_time - start_time) * 1000)
            run.status = TestRunStatus.SUCCESS
            run.completed_at = datetime.utcnow()

            if isinstance(result, dict):
                # Pipeline returns "chunks" not "chunk_count"
                run.chunk_count = result.get("chunks", 0)
                run.summary = result.get("summary")
                run.raw_metadata = json.dumps({
                    "documents": result.get("documents"),
                    "chunks": result.get("chunks"),
                    "vectors_upserted": result.get("vectors_upserted"),
                    "summary": result.get("summary"),
                    "namespace": temp_namespace,
                })

            db.commit()

            # NOTE: We keep the test namespace for querying
            # It can be cleaned up manually or by a future cleanup job

        except Exception as e:
            import traceback
            run.status = TestRunStatus.FAILED
            run.error_message = str(e)
            run.completed_at = datetime.utcnow()
            run.total_duration_ms = int((time.time() - start_time) * 1000)
            run.raw_metadata = json.dumps({
                "error": str(e),
                "traceback": traceback.format_exc(),
            })
            db.commit()

        finally:
            # Clean up temp file
            if local_path and os.path.exists(local_path):
                os.remove(local_path)

    finally:
        db.close()
