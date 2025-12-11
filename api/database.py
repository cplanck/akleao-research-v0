"""Database setup and models."""

from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, ForeignKey, Text, Enum, Integer
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
import enum
import uuid

DATABASE_URL = "sqlite:///./simage.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class ResourceType(str, enum.Enum):
    DOCUMENT = "document"
    WEBSITE = "website"
    GIT_REPOSITORY = "git_repository"


class ResourceStatus(str, enum.Enum):
    PENDING = "pending"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"


class Workspace(Base):
    __tablename__ = "workspaces"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    system_instructions = Column(Text, nullable=True)  # Custom instructions for the AI
    created_at = Column(DateTime, default=datetime.utcnow)

    resources = relationship("Resource", back_populates="workspace", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="workspace", cascade="all, delete-orphan")


class Resource(Base):
    __tablename__ = "resources"

    id = Column(String, primary_key=True, default=generate_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    type = Column(Enum(ResourceType), nullable=False)
    source = Column(String, nullable=False)  # file path, URL, etc.
    filename = Column(String, nullable=True)  # original filename for uploads
    status = Column(Enum(ResourceStatus), default=ResourceStatus.PENDING)
    error_message = Column(Text, nullable=True)
    metadata_ = Column("metadata", Text, nullable=True)  # JSON string for type-specific info
    summary = Column(Text, nullable=True)  # LLM-generated summary of the document content
    created_at = Column(DateTime, default=datetime.utcnow)
    indexed_at = Column(DateTime, nullable=True)  # When indexing completed
    indexing_duration_ms = Column(Integer, nullable=True)  # Duration in milliseconds
    file_size_bytes = Column(Integer, nullable=True)  # File size for documents
    commit_hash = Column(String, nullable=True)  # Git commit SHA for tracking updates

    workspace = relationship("Workspace", back_populates="resources")


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    workspace_id = Column(String, ForeignKey("workspaces.id"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)  # JSON string for source info
    created_at = Column(DateTime, default=datetime.utcnow)

    workspace = relationship("Workspace", back_populates="messages")


def init_db():
    """Create all tables."""
    Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
