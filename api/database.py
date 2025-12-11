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


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class Project(Base):
    """A project contains threads and resources."""
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False)
    system_instructions = Column(Text, nullable=True)  # Custom instructions for the AI
    created_at = Column(DateTime, default=datetime.utcnow)
    last_thread_id = Column(String, nullable=True)  # Last active thread for UI restoration

    resources = relationship("Resource", back_populates="project", cascade="all, delete-orphan")
    threads = relationship("Thread", back_populates="project", cascade="all, delete-orphan")


class Thread(Base):
    """A conversation thread within a project."""
    __tablename__ = "threads"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete

    project = relationship("Project", back_populates="threads")
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan")


class Resource(Base):
    """A document, website, or git repo indexed in a project."""
    __tablename__ = "resources"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
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
    pinecone_namespace = Column(String, nullable=True)  # Namespace used when indexing in Pinecone

    project = relationship("Project", back_populates="resources")


class Message(Base):
    """A chat message in a thread."""
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)  # JSON string for source info
    created_at = Column(DateTime, default=datetime.utcnow)

    thread = relationship("Thread", back_populates="messages")


def init_db():
    """Create all tables and run migrations if needed."""
    # Check if we need to migrate from old schema
    from sqlalchemy import inspect
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    if "workspaces" in existing_tables and "projects" not in existing_tables:
        # Need to migrate from old schema to new schema
        _migrate_workspaces_to_projects()
    else:
        # Fresh install or already migrated
        Base.metadata.create_all(bind=engine)

    # Run incremental migrations for new columns
    _run_incremental_migrations()


def _migrate_workspaces_to_projects():
    """Migrate old workspace-based schema to new project/thread schema."""
    from sqlalchemy import text

    with engine.connect() as conn:
        # Start transaction
        trans = conn.begin()
        try:
            # Create new tables
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS projects (
                    id VARCHAR PRIMARY KEY,
                    name VARCHAR NOT NULL,
                    system_instructions TEXT,
                    created_at DATETIME,
                    last_thread_id VARCHAR
                )
            """))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS threads (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title VARCHAR NOT NULL,
                    created_at DATETIME,
                    updated_at DATETIME,
                    deleted_at DATETIME
                )
            """))

            # Create a default project
            default_project_id = str(uuid.uuid4())
            conn.execute(text("""
                INSERT INTO projects (id, name, system_instructions, created_at)
                VALUES (:id, :name, NULL, :created_at)
            """), {"id": default_project_id, "name": "Default Project", "created_at": datetime.utcnow()})

            # For each workspace, create a thread and migrate messages
            workspaces = conn.execute(text("SELECT id, name, system_instructions, created_at FROM workspaces")).fetchall()

            first_thread_id = None
            for ws in workspaces:
                ws_id, ws_name, ws_instructions, ws_created = ws
                thread_id = str(uuid.uuid4())
                if first_thread_id is None:
                    first_thread_id = thread_id

                # Create thread from workspace
                conn.execute(text("""
                    INSERT INTO threads (id, project_id, title, created_at, updated_at)
                    VALUES (:id, :project_id, :title, :created_at, :updated_at)
                """), {
                    "id": thread_id,
                    "project_id": default_project_id,
                    "title": ws_name,
                    "created_at": ws_created or datetime.utcnow(),
                    "updated_at": datetime.utcnow()
                })

                # Update messages to point to thread instead of workspace
                conn.execute(text("""
                    UPDATE messages SET workspace_id = :thread_id WHERE workspace_id = :ws_id
                """), {"thread_id": thread_id, "ws_id": ws_id})

                # Move resources to project (they were workspace-scoped before)
                conn.execute(text("""
                    UPDATE resources SET workspace_id = :project_id WHERE workspace_id = :ws_id
                """), {"project_id": default_project_id, "ws_id": ws_id})

            # Update last_thread_id on project
            if first_thread_id:
                conn.execute(text("""
                    UPDATE projects SET last_thread_id = :thread_id WHERE id = :project_id
                """), {"thread_id": first_thread_id, "project_id": default_project_id})

            # Rename columns in resources and messages tables
            # For SQLite, we need to recreate the tables

            # Recreate resources table with project_id instead of workspace_id
            conn.execute(text("""
                CREATE TABLE resources_new (
                    id VARCHAR PRIMARY KEY,
                    project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    type VARCHAR NOT NULL,
                    source VARCHAR NOT NULL,
                    filename VARCHAR,
                    status VARCHAR DEFAULT 'pending',
                    error_message TEXT,
                    metadata TEXT,
                    summary TEXT,
                    created_at DATETIME,
                    indexed_at DATETIME,
                    indexing_duration_ms INTEGER,
                    file_size_bytes INTEGER,
                    commit_hash VARCHAR
                )
            """))
            conn.execute(text("""
                INSERT INTO resources_new
                SELECT id, workspace_id, type, source, filename, status, error_message,
                       metadata, summary, created_at, indexed_at, indexing_duration_ms,
                       file_size_bytes, commit_hash
                FROM resources
            """))
            conn.execute(text("DROP TABLE resources"))
            conn.execute(text("ALTER TABLE resources_new RENAME TO resources"))

            # Recreate messages table with thread_id instead of workspace_id
            conn.execute(text("""
                CREATE TABLE messages_new (
                    id VARCHAR PRIMARY KEY,
                    thread_id VARCHAR NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                    role VARCHAR NOT NULL,
                    content TEXT NOT NULL,
                    sources TEXT,
                    created_at DATETIME
                )
            """))
            conn.execute(text("""
                INSERT INTO messages_new
                SELECT id, workspace_id, role, content, sources, created_at
                FROM messages
            """))
            conn.execute(text("DROP TABLE messages"))
            conn.execute(text("ALTER TABLE messages_new RENAME TO messages"))

            # Drop old workspaces table
            conn.execute(text("DROP TABLE workspaces"))

            trans.commit()
            print("[Migration] Successfully migrated workspaces to projects/threads")
        except Exception as e:
            trans.rollback()
            print(f"[Migration] Failed: {e}")
            raise


def _run_incremental_migrations():
    """Run incremental migrations for new columns."""
    from sqlalchemy import text, inspect
    import re

    inspector = inspect(engine)

    # Check if resources table exists
    if "resources" not in inspector.get_table_names():
        return

    # Get columns of resources table
    columns = [col["name"] for col in inspector.get_columns("resources")]

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            # Migration 1: Add pinecone_namespace column if it doesn't exist
            if "pinecone_namespace" not in columns:
                conn.execute(text("ALTER TABLE resources ADD COLUMN pinecone_namespace VARCHAR"))
                print("[Migration] Added pinecone_namespace column to resources")

            # Migration 2: Populate pinecone_namespace for resources that don't have it
            # For documents with paths like "uploads/<workspace_id>/filename.pdf", extract workspace_id
            # For websites and git repos, use the project_id
            resources = conn.execute(text("""
                SELECT id, source, project_id, type, status
                FROM resources
                WHERE pinecone_namespace IS NULL AND status = 'READY'
            """)).fetchall()

            uuid_pattern = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

            for resource in resources:
                r_id, source, project_id, r_type, status = resource

                # Try to extract old workspace_id from source path for documents
                # Format: uploads/<workspace_id>/filename or git_repos/<workspace_id>/...
                namespace = None
                if source:
                    # Look for UUID in the path (it was the workspace_id)
                    match = uuid_pattern.search(source)
                    if match:
                        namespace = match.group(0)

                # If no namespace extracted, use project_id (shouldn't happen for old resources)
                if not namespace:
                    namespace = project_id

                conn.execute(text("""
                    UPDATE resources SET pinecone_namespace = :namespace WHERE id = :id
                """), {"namespace": namespace, "id": r_id})

            if resources:
                print(f"[Migration] Populated pinecone_namespace for {len(resources)} resources")

            trans.commit()
        except Exception as e:
            trans.rollback()
            print(f"[Migration] Incremental migration failed: {e}")
            raise


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
