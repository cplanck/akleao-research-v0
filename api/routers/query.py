"""Query API routes - agentic conversation."""

import os
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from api.database import get_db, Project, Thread
from api.schemas import QueryRequest, QueryResponse, SourceInfo
from rag.embeddings import Embedder
from rag.vectorstore import VectorStore
from rag.retriever import Retriever
from rag.agent import Agent, ResourceInfo

router = APIRouter(tags=["query"])

# Load environment
load_dotenv()


def get_agent():
    """Get agent instance with retriever."""
    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    tavily_key = os.getenv("TAVILY_API_KEY")

    embedder = Embedder(api_key=openai_key)
    vectorstore = VectorStore(
        api_key=pinecone_key,
        index_name=os.getenv("PINECONE_INDEX_NAME", "simage-rag"),
        dimension=embedder.dimensions
    )
    vectorstore.create_index_if_not_exists()
    retriever = Retriever(embedder=embedder, vectorstore=vectorstore)

    return Agent(retriever=retriever, api_key=anthropic_key, tavily_api_key=tavily_key)


def _build_resources_list(project) -> list[ResourceInfo]:
    """Build a list of ResourceInfo from project resources."""
    return [
        ResourceInfo(
            name=r.filename or r.source,
            type=r.type.value,  # "document" or "website"
            status=r.status.value,  # "ready", "pending", "indexing", "failed"
            summary=r.summary  # LLM-generated summary (may be None)
        )
        for r in project.resources
    ]


def _get_resource_namespaces(project) -> list[str]:
    """Get unique namespaces from project resources.

    With the global resource model, each resource has its own namespace
    (resource_id). This handles backward compatibility for old resources
    that may have been indexed with workspace/project IDs.
    """
    namespaces = set()
    for r in project.resources:
        if r.status.value == "ready":  # Only include indexed resources
            if r.pinecone_namespace:
                # Use the stored namespace (resource_id for new resources)
                namespaces.add(r.pinecone_namespace)
            else:
                # Fallback to resource.id for resources without explicit namespace
                namespaces.add(r.id)
    return list(namespaces) if namespaces else []


@router.post("/projects/{project_id}/threads/{thread_id}/query", response_model=QueryResponse)
def query_thread(
    project_id: str,
    thread_id: str,
    request: QueryRequest,
    db: Session = Depends(get_db)
):
    """Query documents in a project using the agent (within a thread context)."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify thread exists and belongs to project
    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    agent = get_agent()

    # Check if project has documents
    has_documents = len(project.resources) > 0

    # Build resources list for agent self-awareness
    resources = _build_resources_list(project)

    # Convert conversation history, filtering out empty messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.conversation_history
        if msg.content.strip()
    ]

    # Get namespaces from project resources
    namespaces = _get_resource_namespaces(project)

    # Use per-resource namespaces (handles old workspace IDs and new project IDs)
    response = agent.chat(
        message=request.question,
        conversation_history=history,
        namespaces=namespaces,
        top_k=request.top_k,
        has_documents=has_documents,
        resources=resources,
        system_instructions=project.system_instructions
    )

    # Update project's last_thread_id
    project.last_thread_id = thread_id
    db.commit()

    # Deduplicate sources by file
    seen_sources = {}
    for r in response.sources:
        if r.source not in seen_sources or r.score > seen_sources[r.source].score:
            seen_sources[r.source] = r

    return QueryResponse(
        answer=response.content,
        sources=[
            SourceInfo(
                content=r.content[:200] + "..." if len(r.content) > 200 else r.content,
                source=r.source,
                score=r.score,
                page_ref=r.metadata.get("page_ref"),
                page_numbers=r.metadata.get("page_numbers"),
                snippet=r.content[:100].strip() + "..." if len(r.content) > 100 else r.content
            )
            for r in seen_sources.values()
        ]
    )


@router.post("/projects/{project_id}/threads/{thread_id}/query/stream")
def query_thread_stream(
    project_id: str,
    thread_id: str,
    request: QueryRequest,
    db: Session = Depends(get_db)
):
    """Query with streaming response using the agent."""
    # Verify project exists
    project = db.query(Project).filter(Project.id == project_id).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Verify thread exists and belongs to project
    thread = db.query(Thread).filter(
        Thread.id == thread_id,
        Thread.project_id == project_id,
        Thread.deleted_at.is_(None)
    ).first()
    if not thread:
        raise HTTPException(status_code=404, detail="Thread not found")

    agent = get_agent()

    # Check if project has documents
    has_documents = len(project.resources) > 0

    # Build resources list for agent self-awareness
    resources = _build_resources_list(project)

    # Convert conversation history, filtering out empty messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.conversation_history
        if msg.content.strip()
    ]

    # Update project's last_thread_id
    project.last_thread_id = thread_id
    db.commit()

    # Get namespaces from project resources
    namespaces = _get_resource_namespaces(project)

    # Use a thread-safe approach for events
    import queue
    import threading

    event_q = queue.Queue()

    def run_agent():
        try:
            for event in agent.chat_stream_events(
                message=request.question,
                conversation_history=history,
                namespaces=namespaces,  # Use per-resource namespaces
                top_k=request.top_k,
                has_documents=has_documents,
                resources=resources,
                system_instructions=project.system_instructions,
                context_only=request.context_only,
            ):
                event_q.put(event)
        except Exception as e:
            from rag.agent import AgentEvent
            event_q.put(AgentEvent("error", {"message": str(e)}))

    def generate():
        # Start agent in background thread
        thread = threading.Thread(target=run_agent)
        thread.start()

        sources_sent = False

        while True:
            try:
                event = event_q.get(timeout=0.1)

                if event.type == "plan":
                    yield f"data: {json.dumps({'type': 'plan', 'category': event.data['category'], 'acknowledgment': event.data['acknowledgment'], 'complexity': event.data['complexity'], 'search_strategy': event.data['search_strategy']})}\n\n"

                elif event.type == "status":
                    yield f"data: {json.dumps({'type': 'status', 'status': event.data['status']})}\n\n"

                elif event.type == "tool_call":
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': event.data['tool'], 'query': event.data.get('query', '')})}\n\n"

                elif event.type == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool': event.data['tool'], 'found': event.data['found'], 'query': event.data.get('query', '')})}\n\n"

                elif event.type == "sources":
                    # Deduplicate sources by file
                    seen = {}
                    for s in event.data["sources"]:
                        if s["source"] not in seen or s["score"] > seen[s["source"]]["score"]:
                            seen[s["source"]] = s
                    yield f"data: {json.dumps({'type': 'sources', 'sources': list(seen.values())})}\n\n"
                    sources_sent = True

                elif event.type == "thinking":
                    yield f"data: {json.dumps({'type': 'thinking', 'content': event.data['content']})}\n\n"

                elif event.type == "chunk":
                    yield f"data: {json.dumps({'type': 'chunk', 'content': event.data['content']})}\n\n"

                elif event.type == "usage":
                    yield f"data: {json.dumps({'type': 'usage', 'input_tokens': event.data['input_tokens'], 'output_tokens': event.data['output_tokens'], 'total_tokens': event.data['total_tokens']})}\n\n"

                elif event.type == "done":
                    if not sources_sent:
                        yield f"data: {json.dumps({'type': 'sources', 'sources': []})}\n\n"
                    yield f"data: {json.dumps({'type': 'done'})}\n\n"
                    break

                elif event.type == "error":
                    yield f"data: {json.dumps({'type': 'error', 'message': event.data['message']})}\n\n"
                    break

            except queue.Empty:
                continue

        thread.join()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
