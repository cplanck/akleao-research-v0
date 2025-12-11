"""Pydantic schemas for API request/response models."""

from datetime import datetime
from pydantic import BaseModel
from api.database import ResourceType, ResourceStatus, MessageRole


# Workspace schemas
class WorkspaceCreate(BaseModel):
    name: str


class WorkspaceUpdate(BaseModel):
    name: str | None = None
    system_instructions: str | None = None


class WorkspaceResponse(BaseModel):
    id: str
    name: str
    system_instructions: str | None = None
    created_at: datetime
    resource_count: int = 0

    class Config:
        from_attributes = True


class WorkspaceDetail(WorkspaceResponse):
    resources: list["ResourceResponse"] = []


# Resource schemas
class ResourceResponse(BaseModel):
    id: str
    workspace_id: str
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

    class Config:
        from_attributes = True


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
    workspace_id: str
    role: MessageRole
    content: str
    sources: list[SourceInfo] | None = None
    created_at: datetime

    class Config:
        from_attributes = True
