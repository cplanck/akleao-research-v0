"""Query API routes - agentic conversation."""

import os
import json
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from typing import Optional
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from api.database import get_db, Project, Thread, Message, User
from api.schemas import QueryRequest, QueryResponse, SourceInfo, SemanticSearchRequest, SemanticSearchResponse, SemanticSearchResult
from api.middleware.auth import get_current_user
from rag.embeddings import Embedder
from rag.vectorstore import VectorStore
from rag.retriever import Retriever
from rag.agent import Agent, ResourceInfo

router = APIRouter(tags=["query"])

# Load environment
load_dotenv()


def get_agent(version: Optional[str] = None):
    """Get agent instance with retriever.

    Args:
        version: Agent version to use ("v1" or "v2"). If None, uses default from env/agent.
    """
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

    return Agent(retriever=retriever, api_key=anthropic_key, tavily_api_key=tavily_key, version=version)


def _build_resources_list(project) -> list[ResourceInfo]:
    """Build a list of ResourceInfo from project resources with metadata.

    Only includes resources with READY status to avoid presenting failed
    or pending resources to the agent.
    """
    import json
    import os

    resources = []
    for r in project.resources:
        # Only include READY resources - skip failed/pending/indexing
        if r.status.value != "ready":
            continue

        # For data files and images, verify the file actually exists
        if r.type.value in ("data_file", "image"):
            if not r.source or not os.path.exists(r.source):
                continue
        resource_info = ResourceInfo(
            name=r.filename or r.source,
            type=r.type.value,  # "document", "website", "data_file", "image"
            status=r.status.value,  # "ready", "pending", "indexing", "failed"
            summary=r.summary,  # LLM-generated summary (may be None)
            id=r.id,  # Resource ID for targeted searches
            file_path=r.source,  # Path to the file for analysis tools
        )

        # Add data file metadata if available
        if r.type.value == "data_file" and r.data_metadata:
            dm = r.data_metadata[0] if isinstance(r.data_metadata, list) else r.data_metadata
            if dm:
                resource_info.row_count = dm.row_count
                if dm.columns_json:
                    try:
                        columns = json.loads(dm.columns_json)
                        resource_info.columns = [c.get("name", "") for c in columns]
                    except:
                        pass

        # Add image metadata if available
        if r.type.value == "image" and r.image_metadata:
            im = r.image_metadata[0] if isinstance(r.image_metadata, list) else r.image_metadata
            if im and im.width and im.height:
                resource_info.dimensions = f"{im.width}x{im.height}"

        resources.append(resource_info)

    return resources


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


def _build_parent_context(thread: Thread, db: Session, max_depth: int = 3) -> str | None:
    """Build context string from ancestor threads for subthreads.

    Returns a context string that explains the full ancestry chain,
    including context texts from each level and recent messages from immediate parent.
    """
    if not thread.parent_thread_id:
        return None

    # Build ancestor chain (walk up parent_thread_id)
    ancestors = []  # List of (parent_thread, context_text_from_child) tuples
    current = thread
    depth = 0

    while current.parent_thread_id and depth < max_depth:
        parent = db.query(Thread).filter(
            Thread.id == current.parent_thread_id,
            Thread.deleted_at.is_(None)
        ).first()
        if not parent:
            break
        # Store the parent and the context_text that spawned the current thread
        ancestors.append((parent, current.context_text))
        current = parent
        depth += 1

    if not ancestors:
        return None

    # Build context string
    context_parts = []

    # Add note about being a subthread with depth info
    context_parts.append("[SUBTHREAD CONTEXT]")
    if len(ancestors) == 1:
        context_parts.append(f"This is a focused exploration nested 1 level deep.")
    else:
        context_parts.append(f"This is a focused exploration nested {len(ancestors)} level(s) deep.")

    # Add ancestry trail (from oldest ancestor to immediate parent)
    context_parts.append("\nAncestry trail:")
    for i, (ancestor, context_text) in enumerate(reversed(ancestors)):
        level = i + 1
        context_parts.append(f"  Level {level}: \"{ancestor.title}\"")
        if context_text and i < len(ancestors) - 1:  # Show context for intermediate levels
            truncated = context_text[:100] + "..." if len(context_text) > 100 else context_text
            context_parts.append(f"    → Diving into: \"{truncated}\"")

    # Add the selected text that spawned this subthread (immediate context)
    if thread.context_text:
        context_parts.append(f"\nThe user wants to dive deeper into this specific text:")
        context_parts.append(f'"{thread.context_text}"')

    # Get recent messages from immediate parent only (to avoid token bloat)
    immediate_parent = ancestors[0][0]
    parent_messages = db.query(Message).filter(
        Message.thread_id == immediate_parent.id
    ).order_by(Message.created_at.desc()).limit(4).all()

    if parent_messages:
        parent_messages.reverse()  # Put in chronological order
        context_parts.append(f"\nRecent context from immediate parent \"{immediate_parent.title}\":")
        for msg in parent_messages:
            role = "User" if msg.role == "user" else "Assistant"
            # Truncate long messages more aggressively
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            context_parts.append(f"- {role}: {content}")

    context_parts.append("\n[END SUBTHREAD CONTEXT]")
    context_parts.append("Please provide a focused, in-depth response about the specific topic the user wants to explore.")

    return "\n".join(context_parts)


@router.post("/projects/{project_id}/threads/{thread_id}/query", response_model=QueryResponse)
def query_thread(
    project_id: str,
    thread_id: str,
    request: QueryRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Query documents in a project using the agent (within a thread context)."""
    # Verify project exists and user owns it
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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

    # Build resources list for agent self-awareness
    resources = _build_resources_list(project)

    # Check what types of resources exist
    has_documents = any(r.type in ("document", "website", "git_repository") for r in resources)
    has_data_files = any(r.type == "data_file" for r in resources)
    has_images = any(r.type == "image" for r in resources)

    # Convert conversation history, filtering out empty messages
    history = [
        {"role": msg.role, "content": msg.content}
        for msg in request.conversation_history
        if msg.content.strip()
    ]

    # Get namespaces from project resources
    namespaces = _get_resource_namespaces(project)

    # Build parent thread context for subthreads
    parent_context = _build_parent_context(thread, db)

    # Combine system instructions with parent context
    combined_instructions = project.system_instructions or ""
    if parent_context:
        if combined_instructions:
            combined_instructions = f"{combined_instructions}\n\n{parent_context}"
        else:
            combined_instructions = parent_context

    # Use per-resource namespaces (handles old workspace IDs and new project IDs)
    response = agent.chat(
        message=request.question,
        conversation_history=history,
        namespaces=namespaces,
        top_k=request.top_k,
        has_documents=has_documents,
        resources=resources,
        system_instructions=combined_instructions if combined_instructions else None
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
    agent_version: Optional[str] = Query(default=None, description="Agent version: 'v1' or 'v2'"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Query with streaming response using the agent.

    Args:
        agent_version: Optional agent version for A/B testing ("v1" or "v2")
    """
    # Verify project exists and user owns it
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
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

    agent = get_agent(version=agent_version)

    # Build resources list for agent self-awareness
    resources = _build_resources_list(project)

    # Check what types of resources exist
    has_documents = any(r.type in ("document", "website", "git_repository") for r in resources)
    has_data_files = any(r.type == "data_file" for r in resources)
    has_images = any(r.type == "image" for r in resources)

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

    # Build parent thread context for subthreads
    parent_context = _build_parent_context(thread, db)

    # Combine system instructions with parent context
    combined_instructions = project.system_instructions or ""
    if parent_context:
        if combined_instructions:
            combined_instructions = f"{combined_instructions}\n\n{parent_context}"
        else:
            combined_instructions = parent_context

    # Create save_finding callback with access to db context
    from api.database import Finding

    def save_finding_callback(content: str, note: str | None) -> dict:
        """Save a finding to the database."""
        db_finding = Finding(
            project_id=project_id,
            thread_id=thread_id,
            content=content,
            note=note
        )
        db.add(db_finding)
        db.commit()
        db.refresh(db_finding)
        return {"id": db_finding.id, "content": db_finding.content}

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
                system_instructions=combined_instructions if combined_instructions else None,
                context_only=request.context_only,
                save_finding_callback=save_finding_callback,
                has_data_files=has_data_files,
                has_images=has_images,
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
                    # Build plan event with base fields
                    plan_data = {
                        'type': 'plan',
                        'category': event.data['category'],
                        'acknowledgment': event.data['acknowledgment'],
                        'complexity': event.data['complexity'],
                        'search_strategy': event.data['search_strategy']
                    }
                    # Add V2 fields if present
                    if 'matched_resource' in event.data:
                        plan_data['matched_resource'] = event.data['matched_resource']
                    if 'resource_confidence' in event.data:
                        plan_data['resource_confidence'] = event.data['resource_confidence']
                    if 'is_followup' in event.data:
                        plan_data['is_followup'] = event.data['is_followup']
                    yield f"data: {json.dumps(plan_data)}\n\n"

                elif event.type == "status":
                    yield f"data: {json.dumps({'type': 'status', 'status': event.data['status']})}\n\n"

                elif event.type == "tool_call":
                    yield f"data: {json.dumps({'type': 'tool_call', 'tool': event.data['tool'], 'query': event.data.get('query', '')})}\n\n"

                elif event.type == "tool_result":
                    result_data = {
                        'type': 'tool_result',
                        'tool': event.data['tool'],
                        'found': event.data['found'],
                        'query': event.data.get('query', '')
                    }
                    # Include save_finding specific fields
                    if event.data['tool'] == 'save_finding':
                        result_data['saved'] = event.data.get('saved', False)
                        result_data['finding_id'] = event.data.get('finding_id')
                        result_data['finding_content'] = event.data.get('finding_content')
                    yield f"data: {json.dumps(result_data)}\n\n"

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
                    input_tokens = event.data.get('input_tokens', 0)
                    output_tokens = event.data.get('output_tokens', 0)
                    total_tokens = event.data.get('total_tokens', input_tokens + output_tokens)
                    yield f"data: {json.dumps({'type': 'usage', 'input_tokens': input_tokens, 'output_tokens': output_tokens, 'total_tokens': total_tokens})}\n\n"

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


def get_retriever():
    """Get retriever instance for semantic search."""
    openai_key = os.getenv("OPENAI_API_KEY")
    pinecone_key = os.getenv("PINECONE_API_KEY")

    embedder = Embedder(api_key=openai_key)
    vectorstore = VectorStore(
        api_key=pinecone_key,
        index_name=os.getenv("PINECONE_INDEX_NAME", "simage-rag"),
        dimension=embedder.dimensions
    )
    vectorstore.create_index_if_not_exists()
    return Retriever(embedder=embedder, vectorstore=vectorstore)


@router.post("/projects/{project_id}/search", response_model=SemanticSearchResponse)
def semantic_search(
    project_id: str,
    request: SemanticSearchRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Perform semantic search across project documents using RAG."""
    # Verify project exists and user owns it
    project = db.query(Project).filter(
        Project.id == project_id,
        Project.user_id == user.id
    ).first()
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    # Get namespaces from project resources
    namespaces = _get_resource_namespaces(project)

    if not namespaces:
        return SemanticSearchResponse(results=[], query=request.query)

    # Perform semantic search
    retriever = get_retriever()
    results = retriever.retrieve(
        query=request.query,
        top_k=request.top_k,
        namespaces=namespaces
    )

    # Convert to response format
    search_results = [
        SemanticSearchResult(
            content=r.content,
            source=r.source,
            score=r.score,
            snippet=r.content[:150].strip() + "..." if len(r.content) > 150 else r.content,
            resource_id=r.metadata.get("resource_id"),
            page_ref=r.metadata.get("page_ref"),
        )
        for r in results
    ]

    return SemanticSearchResponse(results=search_results, query=request.query)
