"""Pydantic schemas for API request/response models."""

from datetime import datetime
from pydantic import BaseModel
from api.database import ResourceType, ResourceStatus, MessageRole


# Project schemas
class ProjectCreate(BaseModel):
    name: str


class ProjectUpdate(BaseModel):
    name: str | None = None
    system_instructions: str | None = None
    last_thread_id: str | None = None


class ProjectResponse(BaseModel):
    id: str
    name: str
    system_instructions: str | None = None
    created_at: datetime
    last_thread_id: str | None = None
    resource_count: int = 0
    thread_count: int = 0

    class Config:
        from_attributes = True


# Thread schemas
class ThreadCreate(BaseModel):
    title: str | None = None  # Auto-generate if not provided


class ThreadUpdate(BaseModel):
    title: str | None = None


class ThreadResponse(BaseModel):
    id: str
    project_id: str
    title: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# Resource schemas
class ResourceResponse(BaseModel):
    id: str
    project_id: str | None  # Now nullable since resources are global
    type: ResourceType
    source: str
    filename: str | None
    status: ResourceStatus
    error_message: str | None
    summary: str | None = None  # LLM-generated summary of the document content
    created_at: datetime
    indexed_at: datetime | None = None
    indexing_duration_ms: int | None = None
    file_size_bytes: int | None = None
    commit_hash: str | None = None  # Git commit SHA for tracking updates
    content_hash: str | None = None  # SHA256 hash for deduplication
    project_count: int = 1  # Number of projects using this resource
    is_shared: bool = False  # True if used by multiple projects

    class Config:
        from_attributes = True


class ResourceLinkRequest(BaseModel):
    """Request to link an existing resource to a project."""
    resource_id: str


class GlobalResourceResponse(ResourceResponse):
    """Resource response with list of projects using it."""
    projects: list[str] = []  # List of project IDs


class UrlResourceCreate(BaseModel):
    url: str


class GitRepoResourceCreate(BaseModel):
    url: str  # Git clone URL (https://github.com/user/repo.git or https://github.com/user/repo)
    branch: str | None = None  # Optional branch, defaults to default branch


# Query schemas
class ConversationMessage(BaseModel):
    role: str  # "user" or "assistant"
    content: str


class QueryRequest(BaseModel):
    question: str
    top_k: int = 5
    conversation_history: list[ConversationMessage] = []
    context_only: bool = False  # When True, only answer from provided documents


class SourceInfo(BaseModel):
    content: str  # The full chunk content
    source: str
    score: float
    page_ref: str | None = None  # e.g., "p. 5" or "pp. 5-7"
    page_numbers: str | None = None  # e.g., "5,6,7" (comma-separated for Pinecone compatibility)
    snippet: str | None = None  # A shorter excerpt for display
    resource_id: str | None = None  # ID of the resource this chunk belongs to
    # Line number info for code files from git repositories
    line_start: int | None = None  # Start line (1-indexed)
    line_end: int | None = None  # End line (1-indexed)
    github_url: str | None = None  # Full GitHub URL with file path and line numbers


class QueryResponse(BaseModel):
    answer: str
    sources: list[SourceInfo]


# Message schemas
class MessageCreate(BaseModel):
    role: MessageRole
    content: str
    sources: list[SourceInfo] | None = None


class MessageResponse(BaseModel):
    id: str
    thread_id: str
    role: MessageRole
    content: str
    sources: list[SourceInfo] | None = None
    created_at: datetime

    class Config:
        from_attributes = True


# Project detail (includes resources and threads)
class ProjectDetail(ProjectResponse):
    resources: list[ResourceResponse] = []
    threads: list[ThreadResponse] = []


# Thread detail (includes messages)
class ThreadDetail(ThreadResponse):
    messages: list[MessageResponse] = []
