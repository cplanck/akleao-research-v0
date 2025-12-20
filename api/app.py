"""FastAPI application."""

import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.database import init_db
from api.routers import projects, threads, resources, query, messages, findings, jobs, notifications, websocket, auth, test_resources

app = FastAPI(
    title="Akleao Research API",
    description="RAG microservice for document ingestion and querying",
    version="0.1.0"
)

# CORS middleware for frontend
# When using credentials (cookies), we must specify exact origins (not "*")
frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
cors_origins = [
    frontend_url,
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]

# Add Vercel domains for production/preview deployments
vercel_url = os.getenv("VERCEL_URL")  # Set by Vercel automatically
if vercel_url:
    cors_origins.append(f"https://{vercel_url}")

# Add any additional origins from environment (comma-separated)
# Example: CORS_ORIGINS=https://akleao.vercel.app,https://custom-domain.com
extra_origins = os.getenv("CORS_ORIGINS", "")
if extra_origins:
    cors_origins.extend([o.strip() for o in extra_origins.split(",") if o.strip()])

# Remove duplicates while preserving order
cors_origins = list(dict.fromkeys(cors_origins))

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,  # Required for httpOnly cookies
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)  # Auth routes (no auth required)
app.include_router(projects.router)
app.include_router(threads.router)
app.include_router(resources.router)
app.include_router(resources.global_router)  # Global resources (library)
app.include_router(query.router)
app.include_router(messages.router)
app.include_router(findings.router)
app.include_router(jobs.router)
app.include_router(notifications.router)
app.include_router(websocket.router)
app.include_router(test_resources.router)


@app.on_event("startup")
def startup():
    """Initialize database on startup."""
    init_db()


@app.get("/")
def root():
    """Health check."""
    return {"status": "ok", "service": "akleao-research"}


@app.get("/health")
def health():
    """Health check endpoint."""
    return {"status": "healthy"}
