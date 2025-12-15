"""Database setup and models."""

import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, DateTime, ForeignKey, Text, Enum, Integer
from sqlalchemy.orm import sessionmaker, relationship, declarative_base
from sqlalchemy.pool import QueuePool
import enum
import uuid


def get_database_url() -> str:
    """Get database URL from environment variables.

    Supports:
    - DATABASE_URL: Direct connection string (e.g., postgresql://user:pass@host/db or sqlite:///./akleao.db)
    - DB_HOST, DB_USER, DB_PASSWORD, DB_NAME, DB_PORT: Component-based PostgreSQL config
    - Fallback: SQLite for local development
    """
    # Direct connection string takes priority
    database_url = os.getenv("DATABASE_URL")
    if database_url:
        return database_url

    # Component-based PostgreSQL connection
    db_host = os.getenv("DB_HOST")
    if db_host:
        db_user = os.getenv("DB_USER", "postgres")
        db_password = os.getenv("DB_PASSWORD", "")
        db_name = os.getenv("DB_NAME", "akleao")
        db_port = os.getenv("DB_PORT", "5432")
        return f"postgresql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    # Default: SQLite for local development
    return "sqlite:///./akleao.db"


def create_db_engine(database_url: str):
    """Create SQLAlchemy engine with appropriate settings for the database type."""
    if database_url.startswith("sqlite"):
        # SQLite-specific settings
        return create_engine(
            database_url,
            connect_args={"check_same_thread": False}
        )
    else:
        # PostgreSQL with connection pooling
        # db-f1-micro has ~25 max connections
        # With 2 API workers + 2 Celery workers = 4 processes
        # pool_size=3 + max_overflow=2 = 5 connections per process = 20 total
        return create_engine(
            database_url,
            poolclass=QueuePool,
            pool_size=3,           # Keep 3 connections open per process
            max_overflow=2,        # Allow up to 2 more temporarily (5 total per process)
            pool_pre_ping=True,    # Verify connections before use
            pool_recycle=300,      # Recycle connections every 5 minutes (prevent stale)
            pool_timeout=10,       # Fail fast after 10 seconds if no connection
        )


DATABASE_URL = get_database_url()
engine = create_db_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def generate_uuid():
    return str(uuid.uuid4())


class ResourceType(str, enum.Enum):
    DOCUMENT = "document"
    WEBSITE = "website"
    GIT_REPOSITORY = "git_repository"
    DATA_FILE = "data_file"  # CSV, Excel, JSON
    IMAGE = "image"  # PNG, JPG, etc.


class ResourceStatus(str, enum.Enum):
    # Stage 1: Upload complete
    PENDING = "pending"      # Legacy - kept for backwards compat, same as UPLOADED
    UPLOADED = "uploaded"    # File saved, basic metadata captured

    # Stage 2: Extraction
    EXTRACTING = "extracting"  # Type-specific extraction in progress
    EXTRACTED = "extracted"    # Extraction complete
    STORED = "stored"          # No extraction possible (binary files)

    # Stage 3: Semantic enrichment
    INDEXING = "indexing"      # RAG indexing or analysis in progress
    INDEXED = "indexed"        # Full RAG indexing complete (documents)
    ANALYZED = "analyzed"      # Data analysis complete (data files)
    DESCRIBED = "described"    # Vision description complete (images)

    # Terminal states
    READY = "ready"            # Fully processed (backwards compat alias)
    PARTIAL = "partial"        # Stage 1+2 complete, Stage 3 failed (still usable!)
    FAILED = "failed"          # Stage 1 or 2 failed (unusable)


class MessageRole(str, enum.Enum):
    USER = "user"
    ASSISTANT = "assistant"


class JobStatus(str, enum.Enum):
    """Status of a background conversation job."""
    PENDING = "pending"      # Job created, not started yet
    RUNNING = "running"      # Agent is processing
    COMPLETED = "completed"  # Response finished successfully
    FAILED = "failed"        # Error occurred
    CANCELLED = "cancelled"  # User cancelled


class NotificationType(str, enum.Enum):
    """Type of notification."""
    JOB_COMPLETED = "job_completed"
    JOB_FAILED = "job_failed"


class User(Base):
    """User account for authentication."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=True)
    is_active = Column(Integer, default=1, nullable=False)  # SQLite boolean
    is_admin = Column(Integer, default=0, nullable=False)  # For future admin features
    created_at = Column(DateTime, default=datetime.utcnow)
    last_login_at = Column(DateTime, nullable=True)

    # Relationships
    projects = relationship("Project", back_populates="user", cascade="all, delete-orphan")


class MagicLinkToken(Base):
    """Temporary tokens for magic link authentication."""
    __tablename__ = "magic_link_tokens"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # Null for new user signup
    email = Column(String, nullable=False, index=True)
    token = Column(String(64), unique=True, nullable=False, index=True)  # SHA256 hash stored
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", backref="magic_link_tokens")


class Project(Base):
    """A project contains threads and resources."""
    __tablename__ = "projects"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True)  # Owner of the project
    name = Column(String, nullable=False)
    system_instructions = Column(Text, nullable=True)  # Custom instructions for the AI
    created_at = Column(DateTime, default=datetime.utcnow)
    last_thread_id = Column(String, nullable=True)  # Last active thread for UI restoration
    findings_summary = Column(Text, nullable=True)  # AI-generated summary of findings
    findings_summary_updated_at = Column(DateTime, nullable=True)  # When summary was last generated

    # Relationships
    user = relationship("User", back_populates="projects")
    # Many-to-many relationship with resources via bridge table
    project_resources = relationship("ProjectResource", back_populates="project", cascade="all, delete-orphan")
    threads = relationship("Thread", back_populates="project", cascade="all, delete-orphan")
    jobs = relationship("ConversationJob", back_populates="project", cascade="all, delete-orphan")
    notifications = relationship("Notification", back_populates="project", cascade="all, delete-orphan")

    @property
    def resources(self):
        """Helper property to get list of Resource objects linked to this project."""
        return [pr.resource for pr in self.project_resources if pr.resource]


class Thread(Base):
    """A conversation thread within a project."""
    __tablename__ = "threads"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    title = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True)  # Soft delete
    # Parent thread support for "Dive Deeper" feature
    parent_thread_id = Column(String, ForeignKey("threads.id", ondelete="SET NULL"), nullable=True)
    parent_message_id = Column(String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    context_text = Column(Text, nullable=True)  # The selected text that spawned this thread

    project = relationship("Project", back_populates="threads")
    messages = relationship("Message", back_populates="thread", cascade="all, delete-orphan", foreign_keys="Message.thread_id")
    parent_thread = relationship("Thread", remote_side="Thread.id", backref="child_threads", foreign_keys=[parent_thread_id])
    parent_message = relationship("Message", foreign_keys=[parent_message_id])


class Resource(Base):
    """A document, website, or git repo - globally scoped, can be shared across projects."""
    __tablename__ = "resources"

    id = Column(String, primary_key=True, default=generate_uuid)
    # project_id kept for backward compat during migration, but nullable now
    project_id = Column(String, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    type = Column(Enum(ResourceType), nullable=False)
    source = Column(String, nullable=False)  # file path, URL, etc.
    filename = Column(String, nullable=True)  # original filename for uploads
    status = Column(Enum(ResourceStatus), default=ResourceStatus.PENDING)
    error_message = Column(Text, nullable=True)
    error_stage = Column(String, nullable=True)  # "extraction" or "indexing" - which stage failed
    metadata_ = Column("metadata", Text, nullable=True)  # JSON string for type-specific info (legacy)
    summary = Column(Text, nullable=True)  # LLM-generated summary of the document content
    created_at = Column(DateTime, default=datetime.utcnow)
    indexed_at = Column(DateTime, nullable=True)  # When indexing completed
    indexing_duration_ms = Column(Integer, nullable=True)  # Duration in milliseconds
    file_size_bytes = Column(Integer, nullable=True)  # File size for documents
    commit_hash = Column(String, nullable=True)  # Git commit SHA for tracking updates
    pinecone_namespace = Column(String, nullable=True)  # Namespace used when indexing in Pinecone
    content_hash = Column(String(64), nullable=True, unique=True, index=True)  # SHA256 hash for deduplication

    # === New fields for unified upload flow ===
    mime_type = Column(String, nullable=True)  # e.g., "application/pdf", "text/csv"
    storage_backend = Column(String, default="local")  # "local" or "gcs"
    extracted_at = Column(DateTime, nullable=True)  # When extraction (Stage 2) completed
    extraction_duration_ms = Column(Integer, nullable=True)  # Stage 2 duration
    extraction_metadata = Column(Text, nullable=True)  # JSON: type-specific extraction data
    chunk_count = Column(Integer, nullable=True)  # Number of chunks indexed (for RAG docs)

    # Many-to-many relationship with projects via bridge table
    project_resources = relationship("ProjectResource", back_populates="resource", cascade="all, delete-orphan")

    @property
    def project_count(self):
        """Number of projects this resource is linked to."""
        return len(self.project_resources)

    @property
    def is_shared(self):
        """True if this resource is used by more than one project."""
        return len(self.project_resources) > 1


class Message(Base):
    """A chat message in a thread."""
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    role = Column(Enum(MessageRole), nullable=False)
    content = Column(Text, nullable=False)
    sources = Column(Text, nullable=True)  # JSON string for source info
    tool_calls = Column(Text, nullable=True)  # JSON string for tool call history
    created_at = Column(DateTime, default=datetime.utcnow)

    thread = relationship("Thread", back_populates="messages", foreign_keys=[thread_id])


class ProjectResource(Base):
    """Bridge table for many-to-many relationship between Projects and Resources."""
    __tablename__ = "project_resources"

    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True)
    resource_id = Column(String, ForeignKey("resources.id", ondelete="CASCADE"), primary_key=True)
    added_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", back_populates="project_resources")
    resource = relationship("Resource", back_populates="project_resources")


class Finding(Base):
    """A key finding saved from a chat response."""
    __tablename__ = "findings"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="SET NULL"), nullable=True)
    message_id = Column(String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    content = Column(Text, nullable=False)  # The saved text
    note = Column(Text, nullable=True)  # Optional user note
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("Project", backref="findings")
    thread = relationship("Thread", backref="findings")
    message = relationship("Message", backref="findings")


class DataResourceMetadata(Base):
    """Schema and statistics for data files (CSV, Excel, JSON)."""
    __tablename__ = "data_resource_metadata"

    id = Column(String, primary_key=True, default=generate_uuid)
    resource_id = Column(String, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Schema information
    columns_json = Column(Text, nullable=True)  # JSON: [{name, dtype, sample_values, null_count}]
    row_count = Column(Integer, nullable=True)
    column_count = Column(Integer, nullable=True)

    # For Excel files with multiple sheets
    sheet_names_json = Column(Text, nullable=True)  # JSON array of sheet names

    # Sample data for LLM context
    sample_rows_json = Column(Text, nullable=True)  # First 5 rows as JSON

    # LLM-generated semantic description (crucial for routing!)
    content_description = Column(Text, nullable=True)  # "Sales data for Q1 2024, contains customer names..."

    # Statistics summary
    numeric_summary_json = Column(Text, nullable=True)  # {column: {min, max, mean, std}}

    resource = relationship("Resource", backref="data_metadata")


class ImageResourceMetadata(Base):
    """Metadata for image files."""
    __tablename__ = "image_resource_metadata"

    id = Column(String, primary_key=True, default=generate_uuid)
    resource_id = Column(String, ForeignKey("resources.id", ondelete="CASCADE"), nullable=False, unique=True)

    # Basic image info
    width = Column(Integer, nullable=True)
    height = Column(Integer, nullable=True)
    format = Column(String, nullable=True)  # PNG, JPEG, etc.

    # Vision-generated description (crucial for routing!)
    vision_description = Column(Text, nullable=True)  # LLM vision analysis of the image

    resource = relationship("Resource", backref="image_metadata")


class ConversationJob(Base):
    """A background job for processing a conversation query.

    This enables persistent conversations that survive page navigation.
    When user submits a question, a job is created and processed by a Celery worker.
    The user can navigate away and return later to see the completed response.
    """
    __tablename__ = "conversation_jobs"

    id = Column(String, primary_key=True, default=generate_uuid)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=False)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)

    # Job state
    status = Column(Enum(JobStatus), default=JobStatus.PENDING, nullable=False)

    # User message that triggered this job
    user_message_id = Column(String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    user_message_content = Column(Text, nullable=False)  # Store content for worker access
    context_only = Column(Integer, default=0, nullable=False)  # 1 if only use document context (no web)

    # Response tracking
    assistant_message_id = Column(String, ForeignKey("messages.id", ondelete="SET NULL"), nullable=True)
    partial_response = Column(Text, nullable=True)  # Accumulated response so far
    sources_json = Column(Text, nullable=True)  # JSON string of sources

    # Error handling
    error_message = Column(Text, nullable=True)
    celery_task_id = Column(String, nullable=True)  # For task management/cancellation

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    last_polled_at = Column(DateTime, nullable=True)  # Track if user is watching (for notification logic)

    # Performance tracking
    token_count = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)

    # Relationships
    thread = relationship("Thread", backref="conversation_jobs")
    project = relationship("Project", back_populates="jobs")
    user_message = relationship("Message", foreign_keys=[user_message_id])
    assistant_message = relationship("Message", foreign_keys=[assistant_message_id])


class Notification(Base):
    """User notification for completed/failed conversation jobs.

    Notifications are created when a job completes while the user is not viewing the thread.
    They appear in the bell icon dropdown and can be marked as read.
    """
    __tablename__ = "notifications"

    id = Column(String, primary_key=True, default=generate_uuid)
    project_id = Column(String, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    thread_id = Column(String, ForeignKey("threads.id", ondelete="CASCADE"), nullable=True)
    job_id = Column(String, ForeignKey("conversation_jobs.id", ondelete="CASCADE"), nullable=True)

    type = Column(Enum(NotificationType), nullable=False)
    title = Column(String, nullable=False)  # e.g., "Response ready in 'Pricing Research'"
    body = Column(Text, nullable=True)  # Preview of the response

    # Read status
    read = Column(Integer, default=0, nullable=False)  # SQLite doesn't have true Boolean, use Integer
    read_at = Column(DateTime, nullable=True)

    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    project = relationship("Project", back_populates="notifications")
    thread = relationship("Thread", backref="notifications")
    job = relationship("ConversationJob", backref="notifications")


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
    import hashlib
    import os

    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    # Check if resources table exists
    if "resources" not in existing_tables:
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
                columns.append("pinecone_namespace")

            # Migration 2: Add content_hash column if it doesn't exist
            if "content_hash" not in columns:
                conn.execute(text("ALTER TABLE resources ADD COLUMN content_hash VARCHAR(64)"))
                print("[Migration] Added content_hash column to resources")
                columns.append("content_hash")

            # Migration 3: Create project_resources bridge table if it doesn't exist
            if "project_resources" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE project_resources (
                        project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        resource_id VARCHAR NOT NULL REFERENCES resources(id) ON DELETE CASCADE,
                        added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        PRIMARY KEY (project_id, resource_id)
                    )
                """))
                print("[Migration] Created project_resources bridge table")

                # Migration 4: Migrate existing resources to bridge table
                # For each resource with a project_id, create an entry in project_resources
                resources_with_project = conn.execute(text("""
                    SELECT id, project_id FROM resources WHERE project_id IS NOT NULL
                """)).fetchall()

                for r_id, project_id in resources_with_project:
                    # Check if entry already exists (shouldn't but be safe)
                    existing = conn.execute(text("""
                        SELECT 1 FROM project_resources
                        WHERE project_id = :project_id AND resource_id = :resource_id
                    """), {"project_id": project_id, "resource_id": r_id}).fetchone()

                    if not existing:
                        conn.execute(text("""
                            INSERT INTO project_resources (project_id, resource_id, added_at)
                            VALUES (:project_id, :resource_id, CURRENT_TIMESTAMP)
                        """), {"project_id": project_id, "resource_id": r_id})

                if resources_with_project:
                    print(f"[Migration] Migrated {len(resources_with_project)} resources to bridge table")

            # Migration 5: Populate pinecone_namespace for resources that don't have it
            # For documents with paths like "uploads/<workspace_id>/filename.pdf", extract workspace_id
            # For websites and git repos, use the project_id
            uuid_pattern = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.I)

            resources = conn.execute(text("""
                SELECT id, source, project_id, type, status
                FROM resources
                WHERE pinecone_namespace IS NULL AND status = 'READY'
            """)).fetchall()

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

            # Migration 6: Compute content_hash for document resources that don't have it
            # Note: PostgreSQL enums use uppercase names (DOCUMENT), SQLite uses lowercase values (document)
            is_postgres = 'postgresql' in str(engine.url)
            doc_type = 'DOCUMENT' if is_postgres else 'document'
            docs_without_hash = conn.execute(text(f"""
                SELECT id, source, type FROM resources
                WHERE content_hash IS NULL AND type = '{doc_type}'
            """)).fetchall()

            hashed_count = 0
            for r_id, source, r_type in docs_without_hash:
                if source and os.path.exists(source):
                    try:
                        sha256 = hashlib.sha256()
                        with open(source, 'rb') as f:
                            for chunk in iter(lambda: f.read(8192), b''):
                                sha256.update(chunk)
                        content_hash = sha256.hexdigest()
                        conn.execute(text("""
                            UPDATE resources SET content_hash = :hash WHERE id = :id
                        """), {"hash": content_hash, "id": r_id})
                        hashed_count += 1
                    except Exception as e:
                        print(f"[Migration] Could not hash resource {r_id}: {e}")

            if hashed_count:
                print(f"[Migration] Computed content_hash for {hashed_count} document resources")

            # Migration 7: Add Thread parent columns for "Dive Deeper" feature
            if "threads" in existing_tables:
                thread_columns = [col["name"] for col in inspector.get_columns("threads")]

                if "parent_thread_id" not in thread_columns:
                    conn.execute(text("ALTER TABLE threads ADD COLUMN parent_thread_id VARCHAR"))
                    print("[Migration] Added parent_thread_id column to threads")

                if "parent_message_id" not in thread_columns:
                    conn.execute(text("ALTER TABLE threads ADD COLUMN parent_message_id VARCHAR"))
                    print("[Migration] Added parent_message_id column to threads")

                if "context_text" not in thread_columns:
                    conn.execute(text("ALTER TABLE threads ADD COLUMN context_text TEXT"))
                    print("[Migration] Added context_text column to threads")

            # Migration 8: Create findings table for Key Findings feature
            if "findings" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE findings (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        thread_id VARCHAR REFERENCES threads(id) ON DELETE SET NULL,
                        message_id VARCHAR REFERENCES messages(id) ON DELETE SET NULL,
                        content TEXT NOT NULL,
                        note TEXT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("[Migration] Created findings table")

            # Migration 9: Create data_resource_metadata table for CSV/Excel/JSON files
            if "data_resource_metadata" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE data_resource_metadata (
                        id VARCHAR PRIMARY KEY,
                        resource_id VARCHAR NOT NULL UNIQUE REFERENCES resources(id) ON DELETE CASCADE,
                        columns_json TEXT,
                        row_count INTEGER,
                        column_count INTEGER,
                        sheet_names_json TEXT,
                        sample_rows_json TEXT,
                        content_description TEXT,
                        numeric_summary_json TEXT
                    )
                """))
                print("[Migration] Created data_resource_metadata table")

            # Migration 10: Create image_resource_metadata table for image files
            if "image_resource_metadata" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE image_resource_metadata (
                        id VARCHAR PRIMARY KEY,
                        resource_id VARCHAR NOT NULL UNIQUE REFERENCES resources(id) ON DELETE CASCADE,
                        width INTEGER,
                        height INTEGER,
                        format VARCHAR,
                        vision_description TEXT
                    )
                """))
                print("[Migration] Created image_resource_metadata table")

            # Migration 11: Create conversation_jobs table for persistent conversations
            if "conversation_jobs" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE conversation_jobs (
                        id VARCHAR PRIMARY KEY,
                        thread_id VARCHAR NOT NULL REFERENCES threads(id) ON DELETE CASCADE,
                        project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        status VARCHAR NOT NULL DEFAULT 'pending',
                        user_message_id VARCHAR REFERENCES messages(id) ON DELETE SET NULL,
                        user_message_content TEXT NOT NULL,
                        assistant_message_id VARCHAR REFERENCES messages(id) ON DELETE SET NULL,
                        partial_response TEXT,
                        sources_json TEXT,
                        error_message TEXT,
                        celery_task_id VARCHAR,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        started_at DATETIME,
                        completed_at DATETIME,
                        last_polled_at DATETIME,
                        token_count INTEGER,
                        duration_ms INTEGER
                    )
                """))
                print("[Migration] Created conversation_jobs table")

            # Migration 12: Create notifications table for job completion alerts
            if "notifications" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE notifications (
                        id VARCHAR PRIMARY KEY,
                        project_id VARCHAR NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                        thread_id VARCHAR REFERENCES threads(id) ON DELETE CASCADE,
                        job_id VARCHAR REFERENCES conversation_jobs(id) ON DELETE CASCADE,
                        type VARCHAR NOT NULL,
                        title VARCHAR NOT NULL,
                        body TEXT,
                        read INTEGER DEFAULT 0 NOT NULL,
                        read_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                print("[Migration] Created notifications table")

            # Migration 13: Add context_only column to conversation_jobs
            if "conversation_jobs" in existing_tables:
                job_columns = [col["name"] for col in inspector.get_columns("conversation_jobs")]
                if "context_only" not in job_columns:
                    conn.execute(text("ALTER TABLE conversation_jobs ADD COLUMN context_only INTEGER DEFAULT 0 NOT NULL"))
                    print("[Migration] Added context_only column to conversation_jobs")

            # Migration 14: Add tool_calls column to messages for persisting tool call history
            if "messages" in existing_tables:
                message_columns = [col["name"] for col in inspector.get_columns("messages")]
                if "tool_calls" not in message_columns:
                    conn.execute(text("ALTER TABLE messages ADD COLUMN tool_calls TEXT"))
                    print("[Migration] Added tool_calls column to messages")

            # Migration 15: Add findings_summary columns to projects
            if "projects" in existing_tables:
                project_columns = [col["name"] for col in inspector.get_columns("projects")]
                if "findings_summary" not in project_columns:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN findings_summary TEXT"))
                    print("[Migration] Added findings_summary column to projects")
                if "findings_summary_updated_at" not in project_columns:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN findings_summary_updated_at DATETIME"))
                    print("[Migration] Added findings_summary_updated_at column to projects")

            # Migration 16: Create users table
            if "users" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE users (
                        id VARCHAR PRIMARY KEY,
                        email VARCHAR UNIQUE NOT NULL,
                        name VARCHAR,
                        is_active INTEGER DEFAULT 1 NOT NULL,
                        is_admin INTEGER DEFAULT 0 NOT NULL,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        last_login_at DATETIME
                    )
                """))
                conn.execute(text("CREATE INDEX ix_users_email ON users(email)"))
                print("[Migration] Created users table")

            # Migration 17: Create magic_link_tokens table
            if "magic_link_tokens" not in existing_tables:
                conn.execute(text("""
                    CREATE TABLE magic_link_tokens (
                        id VARCHAR PRIMARY KEY,
                        user_id VARCHAR REFERENCES users(id) ON DELETE CASCADE,
                        email VARCHAR NOT NULL,
                        token VARCHAR(64) UNIQUE NOT NULL,
                        expires_at DATETIME NOT NULL,
                        used_at DATETIME,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.execute(text("CREATE INDEX ix_magic_link_tokens_email ON magic_link_tokens(email)"))
                conn.execute(text("CREATE INDEX ix_magic_link_tokens_token ON magic_link_tokens(token)"))
                print("[Migration] Created magic_link_tokens table")

            # Migration 18: Add user_id to projects
            if "projects" in existing_tables:
                project_columns = [col["name"] for col in inspector.get_columns("projects")]
                if "user_id" not in project_columns:
                    conn.execute(text("ALTER TABLE projects ADD COLUMN user_id VARCHAR REFERENCES users(id)"))
                    print("[Migration] Added user_id column to projects")

            # Migration 19: Add 3-stage upload columns to resources
            if "resources" in existing_tables:
                # Refresh columns list
                columns = [col["name"] for col in inspector.get_columns("resources")]

                # Detect database type for correct datetime syntax
                is_postgres = 'postgresql' in str(engine.url)
                datetime_type = "TIMESTAMP" if is_postgres else "DATETIME"

                if "error_stage" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN error_stage VARCHAR"))
                    print("[Migration] Added error_stage column to resources")

                if "mime_type" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN mime_type VARCHAR"))
                    print("[Migration] Added mime_type column to resources")

                if "storage_backend" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN storage_backend VARCHAR DEFAULT 'local'"))
                    print("[Migration] Added storage_backend column to resources")

                if "extracted_at" not in columns:
                    conn.execute(text(f"ALTER TABLE resources ADD COLUMN extracted_at {datetime_type}"))
                    print("[Migration] Added extracted_at column to resources")

                if "extraction_duration_ms" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN extraction_duration_ms INTEGER"))
                    print("[Migration] Added extraction_duration_ms column to resources")

                if "extraction_metadata" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN extraction_metadata TEXT"))
                    print("[Migration] Added extraction_metadata column to resources")

                if "chunk_count" not in columns:
                    conn.execute(text("ALTER TABLE resources ADD COLUMN chunk_count INTEGER"))
                    print("[Migration] Added chunk_count column to resources")

            trans.commit()
        except Exception as e:
            trans.rollback()
            print(f"[Migration] Incremental migration failed: {e}")
            raise

    # Migration 20: Add new ResourceStatus enum values for PostgreSQL
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction, so handle separately
    is_postgres = 'postgresql' in str(engine.url)
    if is_postgres:
        # New status values added for 3-stage upload (use uppercase to match existing enum)
        new_status_values = ['UPLOADED', 'EXTRACTING', 'EXTRACTED', 'STORED', 'INDEXED', 'ANALYZED', 'DESCRIBED', 'PARTIAL']

        # Get current enum values
        with engine.connect() as conn:
            result = conn.execute(text("""
                SELECT enumlabel FROM pg_enum e
                JOIN pg_type t ON e.enumtypid = t.oid
                WHERE t.typname = 'resourcestatus'
            """))
            existing_values = {row[0] for row in result}

        # Add missing values (must be outside transaction for PostgreSQL)
        for value in new_status_values:
            if value not in existing_values:
                # Use raw connection with autocommit for ALTER TYPE
                raw_conn = engine.raw_connection()
                try:
                    raw_conn.set_session(autocommit=True)
                    cursor = raw_conn.cursor()
                    cursor.execute(f"ALTER TYPE resourcestatus ADD VALUE IF NOT EXISTS '{value}'")
                    cursor.close()
                    print(f"[Migration] Added '{value}' to resourcestatus enum")
                except Exception as e:
                    print(f"[Migration] Failed to add '{value}' to resourcestatus enum: {e}")
                finally:
                    raw_conn.close()


def get_db():
    """Dependency for FastAPI routes."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_migrations():
    """Run database migrations. Called during deployment."""
    print(f"[Database] Running migrations against: {DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL}")
    init_db()
    print("[Database] Migrations complete")
