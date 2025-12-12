"""Project API routes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from api.database import get_db, Project, Thread
from api.schemas import ProjectCreate, ProjectUpdate, ProjectResponse, ProjectDetail, ThreadResponse


def get_child_count(db: Session, thread_id: str) -> int:
    """Get the number of child threads for a thread."""
    return db.query(Thread).filter(
        Thread.parent_thread_id == thread_id,
        Thread.deleted_at.is_(None)
    ).count()

router = APIRouter(prefix="/projects", tags=["projects"])


@router.post("", response_model=ProjectResponse)
def create_project(project: ProjectCreate, db: Session = Depends(get_db)):
    """Create a new project."""
    db_project = Project(name=project.name)
    db.add(db_project)
    db.commit()
    db.refresh(db_project)
    return ProjectResponse(
        id=db_project.id,
        name=db_project.name,
        system_instructions=db_project.system_instructions,
        created_at=db_project.created_at,
        last_thread_id=db_project.last_thread_id,
        resource_count=0,
        thread_count=0
    )


@router.get("", response_model=list[ProjectResponse])
def list_projects(db: Session = Depends(get_db)):
    """List all projects."""
    projects = db.query(Project).all()
    return [
        ProjectResponse(
            id=p.id,
            name=p.name,
            system_instructions=p.system_instructions,
            created_at=p.created_at,
            last_thread_id=p.last_thread_id,
            resource_count=len(p.resources),
            thread_count=len([t for t in p.threads if t.deleted_at is None])
        )
        for p in projects
    ]


@router.get("/{project_id}", response_model=ProjectDetail)
def get_project(project_id: str, db: Session = Depends(get_db)):
    """Get project details including resources and threads."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Only include non-deleted threads
    active_threads = [t for t in project.threads if t.deleted_at is None]

    return ProjectDetail(
        id=project.id,
        name=project.name,
        system_instructions=project.system_instructions,
        created_at=project.created_at,
        last_thread_id=project.last_thread_id,
        resource_count=len(project.resources),
        thread_count=len(active_threads),
        resources=project.resources,
        threads=[
            ThreadResponse(
                id=t.id,
                project_id=t.project_id,
                title=t.title,
                created_at=t.created_at,
                updated_at=t.updated_at,
                parent_thread_id=t.parent_thread_id,
                context_text=t.context_text,
                child_count=get_child_count(db, t.id)
            )
            for t in active_threads
        ]
    )


@router.patch("/{project_id}", response_model=ProjectResponse)
def update_project(
    project_id: str,
    update: ProjectUpdate,
    db: Session = Depends(get_db)
):
    """Update project settings (name, system instructions, etc.)."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Only update fields that were provided
    if update.name is not None:
        project.name = update.name
    if update.system_instructions is not None:
        project.system_instructions = update.system_instructions
    if update.last_thread_id is not None:
        # Verify thread exists and belongs to this project
        thread = db.query(Thread).filter(
            Thread.id == update.last_thread_id,
            Thread.project_id == project_id,
            Thread.deleted_at.is_(None)
        ).first()
        if thread:
            project.last_thread_id = update.last_thread_id

    db.commit()
    db.refresh(project)

    active_threads = [t for t in project.threads if t.deleted_at is None]

    return ProjectResponse(
        id=project.id,
        name=project.name,
        system_instructions=project.system_instructions,
        created_at=project.created_at,
        last_thread_id=project.last_thread_id,
        resource_count=len(project.resources),
        thread_count=len(active_threads)
    )


@router.delete("/{project_id}")
def delete_project(project_id: str, db: Session = Depends(get_db)):
    """Delete a project and all its resources and threads."""
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # TODO: Also delete vectors from Pinecone namespace

    db.delete(project)
    db.commit()
    return {"status": "deleted", "id": project_id}
