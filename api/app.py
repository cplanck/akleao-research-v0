"""FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.database import init_db
from api.routers import workspaces, resources, query, messages

app = FastAPI(
    title="Simage RAG API",
    description="RAG microservice for document ingestion and querying",
    version="0.1.0"
)

# CORS middleware for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Adjust for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(workspaces.router)
app.include_router(resources.router)
app.include_router(query.router)
app.include_router(
    messages.router,
    prefix="/workspaces/{workspace_id}/messages",
    tags=["messages"]
)


@app.on_event("startup")
def startup():
    """Initialize database on startup."""
    init_db()


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "service": "simage-rag"}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}
