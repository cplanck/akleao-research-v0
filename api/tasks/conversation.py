"""Background task for processing conversation queries."""

import os
import json
from datetime import datetime
from dotenv import load_dotenv

from api.tasks import celery_app, publish_job_event, get_job_state
from api.routers.websocket import publish_project_job_update, publish_global_job_update
from api.database import (
    SessionLocal, ConversationJob, Message, Notification, Thread, Project, Finding,
    JobStatus, NotificationType, MessageRole
)
from rag.embeddings import Embedder
from rag.vectorstore import VectorStore
from rag.retriever import Retriever
from rag.agent import Agent, ResourceInfo

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
        index_name=os.getenv("PINECONE_INDEX_NAME", "akleao-research"),
        dimension=embedder.dimensions
    )
    vectorstore.create_index_if_not_exists()
    retriever = Retriever(embedder=embedder, vectorstore=vectorstore)

    return Agent(retriever=retriever, api_key=anthropic_key, tavily_api_key=tavily_key)


def _build_resources_list(project) -> list[ResourceInfo]:
    """Build a list of ResourceInfo from project resources with metadata.

    Includes all resources except failed ones, so the agent can see files
    that are still processing (uploaded, extracting, indexing, etc.).
    """
    resources = []
    for r in project.resources:
        # Skip only failed resources - show everything else including processing
        if r.status.value == "failed":
            continue

        # For data files and images, verify the file actually exists
        if r.type.value in ("data_file", "image"):
            if not r.source or not os.path.exists(r.source):
                continue

        resource_info = ResourceInfo(
            name=r.filename or r.source,
            type=r.type.value,
            status=r.status.value,
            summary=r.summary,
            id=r.id,
            file_path=r.source,
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
    """Get unique namespaces from project resources."""
    namespaces = set()
    for r in project.resources:
        if r.status.value == "ready":
            if r.pinecone_namespace:
                namespaces.add(r.pinecone_namespace)
            else:
                namespaces.add(r.id)
    return list(namespaces) if namespaces else []


def _build_parent_context(thread: Thread, db, max_depth: int = 3) -> str | None:
    """Build context string from ancestor threads for subthreads."""
    if not thread.parent_thread_id:
        return None

    ancestors = []
    current = thread
    depth = 0

    while current.parent_thread_id and depth < max_depth:
        parent = db.query(Thread).filter(
            Thread.id == current.parent_thread_id,
            Thread.deleted_at.is_(None)
        ).first()
        if not parent:
            break
        ancestors.append((parent, current.context_text))
        current = parent
        depth += 1

    if not ancestors:
        return None

    context_parts = ["[SUBTHREAD CONTEXT]"]
    if len(ancestors) == 1:
        context_parts.append(f"This is a focused exploration nested 1 level deep.")
    else:
        context_parts.append(f"This is a focused exploration nested {len(ancestors)} level(s) deep.")

    context_parts.append("\nAncestry trail:")
    for i, (ancestor, context_text) in enumerate(reversed(ancestors)):
        level = i + 1
        context_parts.append(f"  Level {level}: \"{ancestor.title}\"")
        if context_text and i < len(ancestors) - 1:
            truncated = context_text[:100] + "..." if len(context_text) > 100 else context_text
            context_parts.append(f"    → Diving into: \"{truncated}\"")

    if thread.context_text:
        context_parts.append(f"\nThe user wants to dive deeper into this specific text:")
        context_parts.append(f'"{thread.context_text}"')

    immediate_parent = ancestors[0][0]
    parent_messages = db.query(Message).filter(
        Message.thread_id == immediate_parent.id
    ).order_by(Message.created_at.desc()).limit(4).all()

    if parent_messages:
        parent_messages.reverse()
        context_parts.append(f"\nRecent context from immediate parent \"{immediate_parent.title}\":")
        for msg in parent_messages:
            role = "User" if msg.role == MessageRole.USER else "Assistant"
            content = msg.content[:300] + "..." if len(msg.content) > 300 else msg.content
            context_parts.append(f"- {role}: {content}")

    context_parts.append("\n[END SUBTHREAD CONTEXT]")
    context_parts.append("Please provide a focused, in-depth response about the specific topic the user wants to explore.")

    return "\n".join(context_parts)


@celery_app.task(bind=True, name="process_conversation")
def process_conversation_task(self, job_id: str):
    """
    Background task to process a conversation query.

    This task:
    1. Loads the job and related data from the database
    2. Runs the agent to generate a response
    3. Saves partial responses periodically (every ~500 chars)
    4. Saves the final message to the database
    5. Creates a notification if the user isn't watching

    Args:
        job_id: The ID of the ConversationJob to process

    Returns:
        dict with status, job_id, and message_id (if successful)
    """
    db = SessionLocal()
    job = None

    try:
        # Load job
        job = db.query(ConversationJob).filter(ConversationJob.id == job_id).first()
        if not job:
            return {"status": "error", "message": "Job not found"}

        # Update job to running
        job.status = JobStatus.RUNNING
        job.started_at = datetime.utcnow()
        job.celery_task_id = self.request.id
        db.commit()

        # Publish started event (to job stream)
        publish_job_event(job_id, "status", {"status": "running"})
        # Publish to project channel (for sidebar indicators)
        publish_project_job_update(job.project_id, job.thread_id, "running")
        # Publish to global channel (for app-level WebSocket)
        publish_global_job_update(job.project_id, job.thread_id, job_id, "running")

        # Load project and thread
        project = db.query(Project).filter(Project.id == job.project_id).first()
        thread = db.query(Thread).filter(Thread.id == job.thread_id).first()

        if not project or not thread:
            job.status = JobStatus.FAILED
            job.error_message = "Project or thread not found"
            job.completed_at = datetime.utcnow()
            db.commit()
            return {"status": "error", "message": "Project or thread not found"}

        # Build resources list and namespaces
        resources = _build_resources_list(project)
        namespaces = _get_resource_namespaces(project)

        # Check resource types
        has_documents = any(r.type in ("document", "website", "git_repository") for r in resources)
        has_data_files = any(r.type == "data_file" for r in resources)
        has_images = any(r.type == "image" for r in resources)

        # Load conversation history from thread messages
        messages = db.query(Message).filter(
            Message.thread_id == job.thread_id
        ).order_by(Message.created_at).all()

        history = [
            {"role": msg.role.value, "content": msg.content}
            for msg in messages
            if msg.content.strip()
        ]

        # Build parent context for subthreads
        parent_context = _build_parent_context(thread, db)

        # Combine system instructions
        combined_instructions = project.system_instructions or ""
        if parent_context:
            if combined_instructions:
                combined_instructions = f"{combined_instructions}\n\n{parent_context}"
            else:
                combined_instructions = parent_context

        # Initialize agent
        agent = get_agent()

        # Create save_finding callback with access to db context
        def save_finding_callback(content: str, note: str | None) -> dict:
            """Save a finding to the database."""
            db_finding = Finding(
                project_id=job.project_id,
                thread_id=job.thread_id,
                content=content,
                note=note
            )
            db.add(db_finding)
            db.commit()
            db.refresh(db_finding)
            return {"id": db_finding.id, "content": db_finding.content}

        # Process conversation
        accumulated_content = ""
        all_sources = []
        last_save_length = 0
        # Save every ~500 chars - real-time streaming happens via Redis pub/sub,
        # DB saves are just for backup/recovery, so we can be less frequent
        SAVE_INTERVAL = 500

        for event in agent.chat_stream_events(
            message=job.user_message_content,
            conversation_history=history,
            namespaces=namespaces,
            top_k=5,
            has_documents=has_documents,
            resources=resources,
            system_instructions=combined_instructions if combined_instructions else None,
            context_only=bool(job.context_only),
            save_finding_callback=save_finding_callback,
            has_data_files=has_data_files,
            has_images=has_images,
        ):
            if event.type == "chunk":
                accumulated_content += event.data["content"]
                # Publish chunk to WebSocket subscribers
                publish_job_event(job_id, "chunk", {"content": event.data["content"]})

                # Save partial response periodically (for DB backup)
                if len(accumulated_content) - last_save_length >= SAVE_INTERVAL:
                    job.partial_response = accumulated_content
                    db.commit()
                    last_save_length = len(accumulated_content)

            elif event.type == "sources":
                all_sources = event.data["sources"]
                job.sources_json = json.dumps(all_sources)
                db.commit()
                # Publish sources to WebSocket subscribers
                publish_job_event(job_id, "sources", {"sources": all_sources})

            elif event.type == "usage":
                job.token_count = event.data.get("total_tokens", 0)
                db.commit()
                # Publish usage to WebSocket subscribers
                publish_job_event(job_id, "usage", event.data)

            elif event.type == "thinking":
                # Publish thinking content to WebSocket subscribers
                publish_job_event(job_id, "thinking", {"content": event.data.get("content", "")})

            elif event.type == "plan":
                # Publish plan/acknowledgment to WebSocket subscribers
                publish_job_event(job_id, "plan", event.data)

            elif event.type == "tool_call":
                # Publish tool call to WebSocket subscribers
                publish_job_event(job_id, "tool_call", event.data)

            elif event.type == "tool_result":
                # Publish tool result to WebSocket subscribers
                publish_job_event(job_id, "tool_result", event.data)

            elif event.type == "done":
                break

            elif event.type == "error":
                publish_job_event(job_id, "error", {"message": event.data.get("message", "Unknown error")})
                raise Exception(event.data.get("message", "Unknown error"))

        # Serialize tool calls from Redis activity log
        tool_calls_json = None
        try:
            final_state = get_job_state(job_id)
            activity = final_state.get("activity", [])
            if activity:
                # Process activity into structured tool call records
                tool_calls = []
                tool_call_map = {}  # Map tool names to their in-progress data

                for item in activity:
                    if item.get("type") == "tool_call":
                        tool_name = item.get("name") or item.get("tool")
                        if tool_name:
                            tool_call_map[tool_name] = {
                                "id": item.get("id", ""),
                                "tool": tool_name,
                                "query": item.get("query", ""),
                                "timestamp": item.get("timestamp", 0),
                                "status": "running",
                            }

                    elif item.get("type") == "tool_result":
                        tool_name = item.get("tool")
                        if tool_name and tool_name in tool_call_map:
                            call_data = tool_call_map[tool_name]
                            found_count = item.get("found", 0)
                            call_data["status"] = "complete" if found_count > 0 else "empty"
                            call_data["found"] = found_count
                            if call_data["timestamp"]:
                                call_data["duration_ms"] = int((item.get("timestamp", 0) - call_data["timestamp"]) * 1000)
                            tool_calls.append(call_data)
                            del tool_call_map[tool_name]

                # Add any tool calls that didn't get results
                for call_data in tool_call_map.values():
                    call_data["status"] = "failed"
                    tool_calls.append(call_data)

                if tool_calls:
                    tool_calls_json = json.dumps(tool_calls)
        except Exception as e:
            print(f"[ConversationTask] Failed to serialize tool calls: {e}")

        # Save final assistant message
        sources_for_message = json.dumps(all_sources) if all_sources else None
        assistant_message = Message(
            thread_id=thread.id,
            role=MessageRole.ASSISTANT,
            content=accumulated_content,
            sources=sources_for_message,
            tool_calls=tool_calls_json
        )
        db.add(assistant_message)
        db.commit()
        db.refresh(assistant_message)

        # Update job to completed
        job.status = JobStatus.COMPLETED
        job.completed_at = datetime.utcnow()
        job.assistant_message_id = assistant_message.id
        job.partial_response = accumulated_content
        if job.started_at:
            job.duration_ms = int((job.completed_at - job.started_at).total_seconds() * 1000)
        db.commit()

        # Publish done event with final message info
        publish_job_event(job_id, "done", {
            "status": "completed",
            "message_id": assistant_message.id,
            "content": accumulated_content,
            "sources": all_sources,
        })
        # Publish to project channel (for sidebar indicators)
        publish_project_job_update(job.project_id, job.thread_id, "completed")
        # Publish to global channel (for app-level WebSocket)
        publish_global_job_update(job.project_id, job.thread_id, job_id, "completed")

        # Create notification ONLY if user isn't watching
        # If job was polled within last 10 seconds, user is watching
        should_notify = True
        if job.last_polled_at:
            seconds_since_poll = (datetime.utcnow() - job.last_polled_at).total_seconds()
            if seconds_since_poll < 10:
                should_notify = False

        if should_notify:
            notification = Notification(
                project_id=job.project_id,
                thread_id=job.thread_id,
                job_id=job.id,
                type=NotificationType.JOB_COMPLETED,
                title=f"Response ready in '{thread.title}'",
                body=accumulated_content[:100] + "..." if len(accumulated_content) > 100 else accumulated_content
            )
            db.add(notification)
            db.commit()

        return {
            "status": "completed",
            "job_id": job_id,
            "message_id": assistant_message.id
        }

    except Exception as e:
        # Handle errors
        if job:
            job.status = JobStatus.FAILED
            job.error_message = str(e)
            job.completed_at = datetime.utcnow()
            db.commit()

            # Publish error event
            publish_job_event(job_id, "error", {
                "status": "failed",
                "message": str(e)
            })
            # Publish to project channel (for sidebar indicators)
            publish_project_job_update(job.project_id, job.thread_id, "failed")
            # Publish to global channel (for app-level WebSocket)
            publish_global_job_update(job.project_id, job.thread_id, job_id, "failed")

            # Create failure notification
            thread = db.query(Thread).filter(Thread.id == job.thread_id).first()
            thread_title = thread.title if thread else "Unknown Thread"

            notification = Notification(
                project_id=job.project_id,
                thread_id=job.thread_id,
                job_id=job.id,
                type=NotificationType.JOB_FAILED,
                title=f"Error in '{thread_title}'",
                body=str(e)[:200]
            )
            db.add(notification)
            db.commit()

        raise

    finally:
        db.close()
