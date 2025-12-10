"""Query API routes - agentic conversation."""

import os
import json
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from api.database import get_db, Workspace
from api.schemas import QueryRequest, QueryResponse, SourceInfo
from rag.embeddings import Embedder
from rag.vectorstore import VectorStore
from rag.retriever import Retriever
from rag.agent import Agent, ResourceInfo

router = APIRouter(prefix="/workspaces/{workspace_id}/query", tags=["query"])

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


def _build_resources_list(workspace) -> list[ResourceInfo]:
    """Build a list of ResourceInfo from workspace resources."""
    return [
        ResourceInfo(
            name=r.filename or r.source,
            type=r.type.value,  # "document" or "website"
            status=r.status.value  # "ready", "pending", "indexing", "failed"
        )
        for r in workspace.resources
    ]


@router.post("", response_model=QueryResponse)
def query_workspace(
    workspace_id: str,
    request: QueryRequest,
    db: Session = Depends(get_db)
):
    """Query documents in a workspace using the agent."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    agent = get_agent()

    # Check if workspace has documents
    has_documents = len(workspace.resources) > 0

    # Build resources list for agent self-awareness
    resources = _build_resources_list(workspace)

    # Convert conversation history, filtering out empty messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.conversation_history
        if msg.content.strip()
    ]

    response = agent.chat(
        message=request.question,
        conversation_history=history,
        namespace=workspace_id,
        top_k=request.top_k,
        has_documents=has_documents,
        resources=resources,
        system_instructions=workspace.system_instructions
    )

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


@router.post("/stream")
def query_workspace_stream(
    workspace_id: str,
    request: QueryRequest,
    db: Session = Depends(get_db)
):
    """Query with streaming response using the agent."""
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).first()
    if not workspace:
        raise HTTPException(status_code=404, detail="Workspace not found")

    agent = get_agent()

    # Check if workspace has documents
    has_documents = len(workspace.resources) > 0

    # Build resources list for agent self-awareness
    resources = _build_resources_list(workspace)

    # Convert conversation history, filtering out empty messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.conversation_history
        if msg.content.strip()
    ]

    # Use a thread-safe approach for events
    import queue
    import threading

    event_q = queue.Queue()

    def run_agent():
        try:
            for event in agent.chat_stream_events(
                message=request.question,
                conversation_history=history,
                namespace=workspace_id,
                top_k=request.top_k,
                has_documents=has_documents,
                resources=resources,
                system_instructions=workspace.system_instructions,
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

                if event.type == "status":
                    yield f"data: {json.dumps({'type': 'status', 'status': event.data['status']})}\n\n"

                elif event.type == "tool_call":
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': event.data['tool'], 'query': event.data.get('query', '')})}\n\n"

                elif event.type == "tool_result":
                    yield f"data: {json.dumps({'type': 'tool_result', 'tool': event.data['tool'], 'found': event.data['found']})}\n\n"

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
