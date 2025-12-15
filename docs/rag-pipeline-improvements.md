# RAG Pipeline Improvements Specification

This document outlines proposed improvements to the RAG pipeline, focusing on:
1. Moving from OpenAI to Voyage embeddings with reranking
2. Unified resource upload flow with consistent metadata storage

---

## Current Architecture

### Embeddings
- **Provider**: OpenAI (`text-embedding-3-small`, 1536 dims)
- **File**: `rag/embeddings.py`
- **Cost**: ~$0.02 per 1M tokens

### Retrieval
- **Vector Store**: Pinecone (cosine similarity)
- **Threshold**: 0.3 score minimum
- **Top-K**: 5 results default
- **No reranking** - results returned in vector similarity order

### Resource Upload Flow
- Files are categorized into RAG/DATA/IMAGE
- Each category has a separate indexing function
- Metadata storage varies by type
- Non-RAGable files (DATA, IMAGE) don't go through Pinecone

---

## Proposed Changes

## 1. Voyage Embeddings + Reranker

### Why Voyage?

| Feature | OpenAI | Voyage |
|---------|--------|--------|
| Retrieval quality (MTEB) | 62.3 | **67.1** (voyage-3) |
| Code retrieval | Good | **Best in class** (voyage-code-3) |
| Reranker available | No | **Yes** (rerank-2) |
| Cost (embeddings) | $0.02/1M | $0.06/1M |
| Cost (rerank) | N/A | $0.05/1M |
| Dimensions | 1536 | 1024 (configurable) |

Voyage is specifically optimized for RAG use cases and offers a reranker that significantly improves result quality.

### Implementation

#### 1.1 New Embedder Class

```python
# rag/embeddings.py

import voyageai
from abc import ABC, abstractmethod


class BaseEmbedder(ABC):
    """Abstract base class for embedders."""

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        pass

    @abstractmethod
    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        pass

    @property
    @abstractmethod
    def dimensions(self) -> int:
        pass


class OpenAIEmbedder(BaseEmbedder):
    """OpenAI embeddings (existing implementation)."""

    def __init__(self, api_key: str = None, model: str = "text-embedding-3-small"):
        self.client = OpenAI(api_key=api_key)
        self.model = model
        self._dimensions = {
            "text-embedding-3-small": 1536,
            "text-embedding-3-large": 3072,
        }

    @property
    def dimensions(self) -> int:
        return self._dimensions.get(self.model, 1536)

    def embed_text(self, text: str) -> list[float]:
        response = self.client.embeddings.create(model=self.model, input=text)
        return response.data[0].embedding

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        # ... existing batch implementation


class VoyageEmbedder(BaseEmbedder):
    """Voyage AI embeddings with optional reranking."""

    # Model options:
    # - voyage-3: General purpose (1024 dims, best quality)
    # - voyage-3-lite: Faster, cheaper (512 dims)
    # - voyage-code-3: Optimized for code (1024 dims)
    # - voyage-finance-2: Financial documents
    # - voyage-law-2: Legal documents

    def __init__(
        self,
        api_key: str = None,
        model: str = "voyage-3",
        input_type: str = None  # "document" for indexing, "query" for retrieval
    ):
        self.client = voyageai.Client(api_key=api_key)
        self.model = model
        self.input_type = input_type
        self._dimensions = {
            "voyage-3": 1024,
            "voyage-3-lite": 512,
            "voyage-code-3": 1024,
            "voyage-finance-2": 1024,
            "voyage-law-2": 1024,
        }

    @property
    def dimensions(self) -> int:
        return self._dimensions.get(self.model, 1024)

    def embed_text(self, text: str) -> list[float]:
        result = self.client.embed(
            texts=[text],
            model=self.model,
            input_type=self.input_type
        )
        return result.embeddings[0]

    def embed_texts(self, texts: list[str], parallel: bool = True) -> list[list[float]]:
        """Batch embed with Voyage (supports up to 128 texts per call)."""
        if not texts:
            return []

        batch_size = 128  # Voyage limit
        all_embeddings = []

        for i in range(0, len(texts), batch_size):
            batch = texts[i:i + batch_size]
            result = self.client.embed(
                texts=batch,
                model=self.model,
                input_type=self.input_type
            )
            all_embeddings.extend(result.embeddings)

        return all_embeddings

    def embed_for_indexing(self, texts: list[str]) -> list[list[float]]:
        """Embed documents for storage (uses 'document' input type)."""
        original_type = self.input_type
        self.input_type = "document"
        embeddings = self.embed_texts(texts)
        self.input_type = original_type
        return embeddings

    def embed_for_query(self, text: str) -> list[float]:
        """Embed query for retrieval (uses 'query' input type)."""
        original_type = self.input_type
        self.input_type = "query"
        embedding = self.embed_text(text)
        self.input_type = original_type
        return embedding


# Factory function
def get_embedder(provider: str = "voyage", **kwargs) -> BaseEmbedder:
    """Get embedder by provider name."""
    if provider == "openai":
        return OpenAIEmbedder(**kwargs)
    elif provider == "voyage":
        return VoyageEmbedder(**kwargs)
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")
```

#### 1.2 Reranker Class

```python
# rag/reranker.py

import voyageai
from dataclasses import dataclass


@dataclass
class RerankResult:
    """Result from reranking."""
    index: int  # Original index in input list
    relevance_score: float  # 0.0 to 1.0
    document: str


class VoyageReranker:
    """Rerank search results using Voyage rerank-2 model."""

    def __init__(self, api_key: str = None, model: str = "rerank-2"):
        self.client = voyageai.Client(api_key=api_key)
        self.model = model

    def rerank(
        self,
        query: str,
        documents: list[str],
        top_k: int = None,
        return_documents: bool = True
    ) -> list[RerankResult]:
        """Rerank documents by relevance to query.

        Args:
            query: The search query
            documents: List of document texts to rerank
            top_k: Number of top results to return (None = all)
            return_documents: Include document text in results

        Returns:
            List of RerankResult sorted by relevance (highest first)
        """
        if not documents:
            return []

        result = self.client.rerank(
            query=query,
            documents=documents,
            model=self.model,
            top_k=top_k,
            return_documents=return_documents
        )

        return [
            RerankResult(
                index=r.index,
                relevance_score=r.relevance_score,
                document=r.document if return_documents else ""
            )
            for r in result.results
        ]


class NoOpReranker:
    """Placeholder reranker that returns results unchanged."""

    def rerank(self, query: str, documents: list[str], top_k: int = None, **kwargs) -> list[RerankResult]:
        results = [
            RerankResult(index=i, relevance_score=1.0, document=doc)
            for i, doc in enumerate(documents)
        ]
        if top_k:
            results = results[:top_k]
        return results


def get_reranker(provider: str = "voyage", **kwargs):
    """Get reranker by provider name."""
    if provider == "voyage":
        return VoyageReranker(**kwargs)
    elif provider == "none":
        return NoOpReranker()
    else:
        raise ValueError(f"Unknown reranker provider: {provider}")
```

#### 1.3 Updated Retriever with Reranking

```python
# rag/retriever.py

from .reranker import VoyageReranker, get_reranker


class Retriever:
    """Retrieves relevant context with optional reranking."""

    def __init__(
        self,
        embedder: BaseEmbedder,
        vectorstore: VectorStore,
        reranker: VoyageReranker = None,  # NEW
        top_k: int = 5,
        retrieval_k: int = 20,  # NEW: Retrieve more, then rerank
        score_threshold: float = 0.3,
        rerank_threshold: float = 0.1  # NEW: Minimum rerank score
    ):
        self.embedder = embedder
        self.vectorstore = vectorstore
        self.reranker = reranker
        self.top_k = top_k
        self.retrieval_k = retrieval_k  # Over-fetch for reranking
        self.score_threshold = score_threshold
        self.rerank_threshold = rerank_threshold

    def retrieve(
        self,
        query: str,
        top_k: int = None,
        namespace: str = "",
        namespaces: list[str] = None,
        filter: dict = None,
        use_reranker: bool = True  # NEW
    ) -> list[RetrievalResult]:
        """Retrieve with optional reranking."""

        # Use query-optimized embedding
        if hasattr(self.embedder, 'embed_for_query'):
            query_embedding = self.embedder.embed_for_query(query)
        else:
            query_embedding = self.embedder.embed_text(query)

        ns_list = namespaces if namespaces else ([namespace] if namespace else [""])
        k = top_k or self.top_k

        # If reranking, retrieve more candidates
        retrieval_k = self.retrieval_k if (self.reranker and use_reranker) else k

        all_results = []
        for ns in ns_list:
            results = self.vectorstore.query(
                embedding=query_embedding,
                top_k=retrieval_k,
                namespace=ns,
                filter=filter
            )
            all_results.extend(results)

        # Sort by vector score and deduplicate
        all_results.sort(key=lambda x: x["score"], reverse=True)
        seen_ids = set()
        unique_results = []
        for r in all_results:
            if r["id"] not in seen_ids:
                seen_ids.add(r["id"])
                unique_results.append(r)
        all_results = unique_results[:retrieval_k]

        # Filter by vector score threshold
        all_results = [r for r in all_results if r["score"] >= self.score_threshold]

        # Rerank if available
        if self.reranker and use_reranker and all_results:
            documents = [r["content"] for r in all_results]
            reranked = self.reranker.rerank(
                query=query,
                documents=documents,
                top_k=k
            )

            # Build results in reranked order
            retrieved = []
            for rr in reranked:
                if rr.relevance_score >= self.rerank_threshold:
                    original = all_results[rr.index]
                    retrieved.append(RetrievalResult(
                        content=original["content"],
                        source=original["source"],
                        score=rr.relevance_score,  # Use rerank score
                        metadata={
                            **original["metadata"],
                            "vector_score": original["score"],  # Preserve original
                            "rerank_score": rr.relevance_score
                        }
                    ))
            return retrieved

        # No reranking - return vector results
        return [
            RetrievalResult(
                content=r["content"],
                source=r["source"],
                score=r["score"],
                metadata=r["metadata"]
            )
            for r in all_results[:k]
        ]
```

#### 1.4 Configuration

```python
# rag/config.py

from dataclasses import dataclass
from typing import Literal


@dataclass
class RAGConfig:
    """RAG pipeline configuration."""

    # Embedding provider
    embedding_provider: Literal["openai", "voyage"] = "voyage"
    embedding_model: str = "voyage-3"

    # Reranking
    rerank_enabled: bool = True
    rerank_model: str = "rerank-2"

    # Retrieval
    top_k: int = 5
    retrieval_k: int = 20  # Candidates before reranking
    score_threshold: float = 0.3
    rerank_threshold: float = 0.1

    # Chunking
    chunk_size: int = 500
    chunk_overlap: int = 50


# Load from environment
def get_config() -> RAGConfig:
    return RAGConfig(
        embedding_provider=os.getenv("EMBEDDING_PROVIDER", "voyage"),
        embedding_model=os.getenv("EMBEDDING_MODEL", "voyage-3"),
        rerank_enabled=os.getenv("RERANK_ENABLED", "true").lower() == "true",
    )
```

#### 1.5 Migration Strategy

Since you're changing embedding models, existing vectors won't be compatible. Options:

**Option A: Fresh Start (Recommended for smaller deployments)**
- Delete existing Pinecone index
- Re-index all resources with Voyage

**Option B: Dual Index (Zero downtime)**
- Create new Pinecone index with Voyage embeddings
- Re-index resources in background
- Switch traffic once complete
- Delete old index

**Option C: Namespace Migration**
- Use a new namespace prefix for Voyage (`v2_<resource_id>`)
- Gradually migrate resources
- Update retriever to check both namespaces

---

## 2. Unified Resource Upload Flow

### Current Problems

1. **Inconsistent metadata** - Each file type stores different fields
2. **No universal file info** - Size, MIME type not always captured
3. **Binary categorization** - "RAGable" vs "not RAGable" is limiting
4. **No fallback** - If RAG fails, resource is marked FAILED (unusable)

### Proposed Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                     UPLOAD FILE                                  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 1: Universal Metadata (ALWAYS runs, synchronous)        │
│  ─────────────────────────────────────────────────────────────  │
│  • filename, file_size_bytes, mime_type                         │
│  • content_hash (SHA256)                                        │
│  • upload_timestamp                                             │
│  • detected_category (rag, data, image, binary, unknown)        │
│  • Status: UPLOADED (new status)                                │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 2: Type-Specific Extraction (Background task)            │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  RAG Documents (PDF, DOCX, MD, TXT):                           │
│    • page_count, word_count                                     │
│    • detected_language                                          │
│    • has_tables, has_images                                     │
│    • Status: EXTRACTED                                          │
│                                                                 │
│  Data Files (CSV, Excel, JSON):                                 │
│    • row_count, column_count                                    │
│    • columns_schema [{name, dtype, nulls, samples}]             │
│    • sheet_names (Excel)                                        │
│    • Status: EXTRACTED                                          │
│                                                                 │
│  Images (PNG, JPG, GIF):                                        │
│    • width, height, format                                      │
│    • Status: EXTRACTED                                          │
│                                                                 │
│  Binary/Unknown:                                                │
│    • Just store metadata from Stage 1                           │
│    • Status: STORED (can't extract more)                        │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  STAGE 3: Semantic Enrichment (Background task, optional)       │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  RAG Documents:                                                 │
│    • Chunking → Embedding → Pinecone                           │
│    • LLM summary                                                │
│    • Status: INDEXED                                            │
│                                                                 │
│  Data Files:                                                    │
│    • LLM content description                                    │
│    • Numeric statistics                                         │
│    • Status: ANALYZED                                           │
│                                                                 │
│  Images:                                                        │
│    • Vision description                                         │
│    • Status: DESCRIBED                                          │
│                                                                 │
│  If Stage 3 FAILS:                                              │
│    • Keep Stage 1 + 2 metadata                                  │
│    • Status: PARTIAL (not FAILED!)                              │
│    • Agent can still see file exists, use read_resource         │
└─────────────────────────────────────────────────────────────────┘
```

### New Status Enum

```python
class ResourceStatus(str, enum.Enum):
    # Stage 1 complete
    UPLOADED = "uploaded"      # File saved, basic metadata captured

    # Stage 2 states
    EXTRACTING = "extracting"  # Type-specific extraction in progress
    EXTRACTED = "extracted"    # Extraction complete (for RAG/DATA/IMAGE)
    STORED = "stored"          # No extraction possible (binary files)

    # Stage 3 states
    INDEXING = "indexing"      # Semantic enrichment in progress
    INDEXED = "indexed"        # Full RAG indexing complete (documents)
    ANALYZED = "analyzed"      # Data analysis complete (data files)
    DESCRIBED = "described"    # Vision description complete (images)

    # Terminal states
    READY = "ready"            # Alias for "fully processed" (backwards compat)
    PARTIAL = "partial"        # Stage 1+2 complete, Stage 3 failed
    FAILED = "failed"          # Stage 1 or 2 failed (unusable)
```

### Updated Resource Model

```python
class Resource(Base):
    __tablename__ = "resources"

    id = Column(String, primary_key=True, default=generate_uuid)

    # === STAGE 1: Universal Metadata (always populated) ===
    filename = Column(String, nullable=False)
    file_size_bytes = Column(Integer, nullable=False)
    mime_type = Column(String, nullable=True)  # e.g., "application/pdf"
    content_hash = Column(String(64), nullable=False)  # SHA256
    detected_category = Column(String, nullable=False)  # "rag", "data", "image", "binary"

    # Storage
    source = Column(String, nullable=False)  # File path in storage
    storage_backend = Column(String, default="local")  # "local" or "gcs"

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    extracted_at = Column(DateTime, nullable=True)
    indexed_at = Column(DateTime, nullable=True)

    # Status tracking
    status = Column(Enum(ResourceStatus), default=ResourceStatus.UPLOADED)
    error_message = Column(Text, nullable=True)
    error_stage = Column(String, nullable=True)  # "extraction" or "indexing"

    # === STAGE 2: Type-Specific Metadata (JSON) ===
    extraction_metadata = Column(Text, nullable=True)  # JSON blob
    # For RAG: {"page_count": 10, "word_count": 5000, "has_tables": true}
    # For Data: {"row_count": 1000, "columns": [...], "sheet_names": [...]}
    # For Image: {"width": 1920, "height": 1080, "format": "PNG"}

    # === STAGE 3: Semantic Enrichment ===
    summary = Column(Text, nullable=True)  # LLM-generated
    pinecone_namespace = Column(String, nullable=True)  # Only for RAG docs
    chunk_count = Column(Integer, nullable=True)  # Only for RAG docs

    # Backwards compatibility
    type = Column(Enum(ResourceType), nullable=False)  # Keep for now

    # Processing metrics
    extraction_duration_ms = Column(Integer, nullable=True)
    indexing_duration_ms = Column(Integer, nullable=True)
```

### Implementation

#### Stage 1: Upload Handler (Synchronous)

```python
# api/routers/resources.py

@router.post("", response_model=ResourceResponse)
async def add_resource(
    project_id: str,
    file: UploadFile = File(...),
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Upload a resource with universal metadata capture."""

    # Validate project ownership
    project = get_user_project(db, project_id, user.id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Read file content
    file_content = await file.read()
    file_size = len(file_content)

    # === STAGE 1: Universal Metadata ===
    content_hash = compute_content_hash(content=file_content)
    mime_type = detect_mime_type(file_content, file.filename)
    detected_category = detect_file_category(file.filename, mime_type)
    resource_type = get_resource_type_from_category(detected_category)

    # Check for duplicates
    existing = db.query(Resource).filter(
        Resource.content_hash == content_hash
    ).first()

    if existing and existing.status in (ResourceStatus.READY, ResourceStatus.INDEXED,
                                         ResourceStatus.ANALYZED, ResourceStatus.DESCRIBED):
        _link_resource_to_project(db, existing, project_id)
        return existing

    # Save to storage
    storage = get_storage()
    file_path = storage.save(project_id, file.filename, file_content)

    # Create resource with Stage 1 metadata
    resource = Resource(
        filename=file.filename,
        file_size_bytes=file_size,
        mime_type=mime_type,
        content_hash=content_hash,
        detected_category=detected_category.value,
        source=str(file_path),
        storage_backend=storage.backend_name,
        type=resource_type,
        status=ResourceStatus.UPLOADED
    )
    db.add(resource)
    db.commit()
    db.refresh(resource)

    # Link to project
    _link_resource_to_project(db, resource, project_id)

    # === Trigger Stage 2 + 3 in background ===
    background_tasks.add_task(
        process_resource,
        resource_id=resource.id,
        file_path=str(file_path),
        category=detected_category
    )

    return resource


def detect_mime_type(content: bytes, filename: str) -> str:
    """Detect MIME type from content and filename."""
    import magic

    # Try magic bytes first
    mime = magic.from_buffer(content, mime=True)
    if mime and mime != "application/octet-stream":
        return mime

    # Fallback to extension
    ext = Path(filename).suffix.lower()
    mime_map = {
        ".pdf": "application/pdf",
        ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".csv": "text/csv",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".json": "application/json",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".gif": "image/gif",
        ".md": "text/markdown",
        ".txt": "text/plain",
    }
    return mime_map.get(ext, "application/octet-stream")
```

#### Stage 2 + 3: Background Processing

```python
# api/routers/resources.py

async def process_resource(resource_id: str, file_path: str, category: FileCategory):
    """Process resource through Stage 2 (extraction) and Stage 3 (enrichment)."""
    db = SessionLocal()

    try:
        resource = db.query(Resource).filter(Resource.id == resource_id).first()
        if not resource:
            return

        # === STAGE 2: Extraction ===
        resource.status = ResourceStatus.EXTRACTING
        db.commit()

        extraction_start = time.time()

        try:
            if category == FileCategory.RAG:
                extraction_meta = extract_document_metadata(file_path)
            elif category == FileCategory.DATA:
                extraction_meta = extract_data_metadata(file_path)
            elif category == FileCategory.IMAGE:
                extraction_meta = extract_image_metadata(file_path)
            else:
                # Binary/unknown - no extraction possible
                resource.status = ResourceStatus.STORED
                db.commit()
                return

            resource.extraction_metadata = json.dumps(extraction_meta)
            resource.extraction_duration_ms = int((time.time() - extraction_start) * 1000)
            resource.extracted_at = datetime.utcnow()
            resource.status = ResourceStatus.EXTRACTED
            db.commit()

        except Exception as e:
            resource.status = ResourceStatus.FAILED
            resource.error_message = str(e)
            resource.error_stage = "extraction"
            db.commit()
            return

        # === STAGE 3: Semantic Enrichment ===
        resource.status = ResourceStatus.INDEXING
        db.commit()

        indexing_start = time.time()

        try:
            if category == FileCategory.RAG:
                result = index_document_to_pinecone(resource_id, file_path)
                resource.pinecone_namespace = resource_id
                resource.chunk_count = result.get("chunk_count")
                resource.summary = result.get("summary")
                resource.status = ResourceStatus.INDEXED

            elif category == FileCategory.DATA:
                result = analyze_data_file(file_path)
                resource.summary = result.get("description")
                # Update extraction_metadata with stats
                meta = json.loads(resource.extraction_metadata or "{}")
                meta["statistics"] = result.get("statistics")
                resource.extraction_metadata = json.dumps(meta)
                resource.status = ResourceStatus.ANALYZED

            elif category == FileCategory.IMAGE:
                result = describe_image(file_path)
                resource.summary = result.get("description")
                resource.status = ResourceStatus.DESCRIBED

            resource.indexing_duration_ms = int((time.time() - indexing_start) * 1000)
            resource.indexed_at = datetime.utcnow()
            db.commit()

        except Exception as e:
            # Stage 3 failed, but Stage 1+2 succeeded
            # Keep the resource usable with partial status
            resource.status = ResourceStatus.PARTIAL
            resource.error_message = f"Enrichment failed: {str(e)}"
            resource.error_stage = "indexing"
            db.commit()
            print(f"[Resource {resource_id}] Stage 3 failed, kept as PARTIAL: {e}")

    finally:
        db.close()


def extract_document_metadata(file_path: str) -> dict:
    """Extract metadata from RAG-able documents."""
    ext = Path(file_path).suffix.lower()

    if ext == ".pdf":
        import pypdf
        reader = pypdf.PdfReader(file_path)
        page_count = len(reader.pages)
        word_count = sum(len(page.extract_text().split()) for page in reader.pages)
        return {
            "page_count": page_count,
            "word_count": word_count,
            "has_tables": False,  # Could detect with more analysis
            "has_images": any(page.images for page in reader.pages)
        }

    elif ext == ".docx":
        import docx
        doc = docx.Document(file_path)
        word_count = sum(len(p.text.split()) for p in doc.paragraphs)
        return {
            "page_count": None,  # DOCX doesn't have fixed pages
            "word_count": word_count,
            "paragraph_count": len(doc.paragraphs),
            "has_tables": len(doc.tables) > 0
        }

    elif ext in (".md", ".txt"):
        with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        return {
            "word_count": len(content.split()),
            "line_count": content.count("\n") + 1,
            "char_count": len(content)
        }

    return {}


def extract_data_metadata(file_path: str) -> dict:
    """Extract metadata from data files."""
    import pandas as pd

    ext = Path(file_path).suffix.lower()

    if ext == ".csv":
        df = pd.read_csv(file_path, nrows=10000)
    elif ext in (".xlsx", ".xls"):
        xl = pd.ExcelFile(file_path)
        df = pd.read_excel(xl, nrows=10000)
        sheet_names = xl.sheet_names
    elif ext == ".json":
        df = pd.read_json(file_path)
        df = df.head(10000)
    elif ext == ".parquet":
        df = pd.read_parquet(file_path)
        df = df.head(10000)
    else:
        raise ValueError(f"Unsupported data format: {ext}")

    # Build column schema
    columns = []
    for col in df.columns:
        columns.append({
            "name": col,
            "dtype": str(df[col].dtype),
            "null_count": int(df[col].isnull().sum()),
            "sample_values": df[col].dropna().head(3).tolist()
        })

    result = {
        "row_count": len(df),
        "column_count": len(df.columns),
        "columns": columns
    }

    if ext in (".xlsx", ".xls"):
        result["sheet_names"] = sheet_names

    return result


def extract_image_metadata(file_path: str) -> dict:
    """Extract metadata from images."""
    from PIL import Image

    with Image.open(file_path) as img:
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode  # RGB, RGBA, L, etc.
        }
```

### Benefits of New Flow

1. **Graceful degradation** - If RAG fails, file is still usable
2. **Consistent metadata** - All files have size, type, hash
3. **Better agent awareness** - `list_resources` shows all files, even non-RAG
4. **Faster initial response** - Stage 1 is synchronous, user sees file immediately
5. **Clearer status** - Know exactly what stage processing is in
6. **Easier debugging** - `error_stage` tells you where it failed

---

## 3. Implementation Priority

### Phase 1: Quick Wins
1. Add `mime_type` to Resource model
2. Add `PARTIAL` status for graceful failures
3. Update `list_resources` tool to show all statuses

### Phase 2: Voyage Migration
4. Implement VoyageEmbedder class
5. Implement VoyageReranker class
6. Update Retriever with reranking
7. Create new Pinecone index
8. Migration script for existing resources

### Phase 3: Unified Upload Flow
9. Implement 3-stage processing
10. Add extraction_metadata JSON field
11. Update background tasks
12. Update frontend for new statuses

---

## 4. Environment Variables

```bash
# Embeddings
EMBEDDING_PROVIDER=voyage  # or "openai"
VOYAGE_API_KEY=pa-xxxxx
EMBEDDING_MODEL=voyage-3

# Reranking
RERANK_ENABLED=true
RERANK_MODEL=rerank-2

# Retrieval
RETRIEVAL_TOP_K=5
RETRIEVAL_CANDIDATES=20  # Before reranking
SCORE_THRESHOLD=0.3
RERANK_THRESHOLD=0.1
```

---

## 5. Cost Comparison

| Operation | OpenAI | Voyage | Change |
|-----------|--------|--------|--------|
| 1M tokens embedded | $0.02 | $0.06 | +$0.04 |
| 1M tokens reranked | N/A | $0.05 | +$0.05 |
| **Total per 1M** | $0.02 | $0.11 | +$0.09 |

**But**: Voyage's better retrieval quality means fewer failed searches, less re-querying, and happier users. The reranker also reduces noise in results, leading to better LLM responses.
