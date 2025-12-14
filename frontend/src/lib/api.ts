const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// WebSocket base URL (convert http to ws)
const WS_BASE = API_BASE.replace(/^http/, "ws");

/**
 * Custom fetch wrapper that includes credentials and handles 401 errors.
 * Redirects to /login on authentication failure.
 */
async function fetchWithAuth(
  url: string,
  options: RequestInit = {}
): Promise<Response> {
  const res = await fetch(url, {
    ...options,
    credentials: "include",
  });

  // Handle 401 by redirecting to login
  if (res.status === 401) {
    // Only redirect if we're in a browser context
    if (typeof window !== "undefined") {
      window.location.href = "/login";
    }
    throw new Error("Not authenticated");
  }

  return res;
}

// Project types
export interface Project {
  id: string;
  name: string;
  system_instructions: string | null;
  created_at: string;
  last_thread_id: string | null;
  resource_count: number;
  thread_count: number;
  findings_summary: string | null;
  findings_summary_updated_at: string | null;
}

export interface Thread {
  id: string;
  project_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  parent_thread_id: string | null;
  context_text: string | null;
  child_count: number;
}

export interface ThreadDetail extends Thread {
  messages: Message[];
}

// Data file metadata (CSV, Excel, JSON)
export interface DataFileMetadata {
  row_count: number | null;
  column_count: number | null;
  columns: Array<{
    name: string;
    dtype: string;
    sample_values: string[];
  }> | null;
  content_description: string | null;
}

// Image metadata
export interface ImageMetadata {
  width: number | null;
  height: number | null;
  format: string | null;
  vision_description: string | null;
}

export interface Resource {
  id: string;
  project_id: string | null;  // Now nullable since resources are global
  type: "document" | "website" | "git_repository" | "data_file" | "image";
  source: string;
  filename: string | null;
  status: "pending" | "indexing" | "ready" | "failed";
  error_message: string | null;
  summary: string | null;
  created_at: string;
  indexed_at: string | null;
  indexing_duration_ms: number | null;
  file_size_bytes: number | null;
  commit_hash: string | null;
  content_hash: string | null;  // SHA256 hash for deduplication
  project_count: number;  // How many projects use this resource
  is_shared: boolean;  // True if used by multiple projects
  // New metadata for data files and images
  data_metadata?: DataFileMetadata | null;
  image_metadata?: ImageMetadata | null;
}

// Global resource with list of projects using it
export interface GlobalResource extends Resource {
  projects: string[];  // List of project IDs using this resource
}

// Response from unlinking a resource
export interface UnlinkResponse {
  status: string;
  id: string;
  orphaned: boolean;
  message?: string;
}

export interface ProjectDetail extends Project {
  resources: Resource[];
  threads: Thread[];
}

export interface SourceInfo {
  content: string;
  source: string;
  score: number;
  page_ref?: string | null;
  page_numbers?: string | null;
  snippet?: string | null;
  resource_id?: string | null;
  line_start?: number | null;
  line_end?: number | null;
  github_url?: string | null;
}

export interface QueryResponse {
  answer: string;
  sources: SourceInfo[];
}

// Projects
export async function listProjects(): Promise<Project[]> {
  const res = await fetchWithAuth(`${API_BASE}/projects`);
  if (!res.ok) throw new Error("Failed to fetch projects");
  return res.json();
}

export async function createProject(name: string): Promise<Project> {
  const res = await fetchWithAuth(`${API_BASE}/projects`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to create project");
  return res.json();
}

export async function getProject(id: string): Promise<ProjectDetail> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${id}`);
  if (!res.ok) throw new Error("Failed to fetch project");
  return res.json();
}

export async function deleteProject(id: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${id}`, { method: "DELETE" });
  if (!res.ok) throw new Error("Failed to delete project");
}

export async function updateProject(
  id: string,
  updates: { name?: string; system_instructions?: string; last_thread_id?: string }
): Promise<Project> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update project");
  return res.json();
}

// Threads
export async function listThreads(projectId: string): Promise<Thread[]> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads`);
  if (!res.ok) throw new Error("Failed to fetch threads");
  return res.json();
}

export async function createThread(projectId: string, title?: string): Promise<Thread> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: title || null }),
  });
  if (!res.ok) throw new Error("Failed to create thread");
  return res.json();
}

export async function getThread(projectId: string, threadId: string): Promise<ThreadDetail> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}`);
  if (!res.ok) throw new Error("Failed to fetch thread");
  return res.json();
}

export async function updateThread(
  projectId: string,
  threadId: string,
  updates: { title?: string }
): Promise<Thread> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update thread");
  return res.json();
}

export async function deleteThread(projectId: string, threadId: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete thread");
}

export async function generateThreadTitle(
  projectId: string,
  threadId: string,
  message: string
): Promise<Thread> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/generate-title`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    }
  );
  if (!res.ok) throw new Error("Failed to generate thread title");
  return res.json();
}

// Resources
export async function uploadResource(
  projectId: string,
  file: File
): Promise<Resource> {
  const formData = new FormData();
  formData.append("file", file);

  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/resources`, {
    method: "POST",
    body: formData,
  });
  if (!res.ok) throw new Error("Failed to upload resource");
  return res.json();
}

export async function getResource(
  projectId: string,
  resourceId: string
): Promise<Resource> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/resources/${resourceId}`
  );
  if (!res.ok) throw new Error("Failed to fetch resource");
  return res.json();
}

export async function deleteResource(
  projectId: string,
  resourceId: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/resources/${resourceId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to delete resource");
}

export async function addUrlResource(
  projectId: string,
  url: string
): Promise<Resource> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/resources/url`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url }),
  });
  if (!res.ok) throw new Error("Failed to add URL resource");
  return res.json();
}

export async function addGitResource(
  projectId: string,
  url: string,
  branch?: string
): Promise<Resource> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/resources/git`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ url, branch: branch || null }),
  });
  if (!res.ok) throw new Error("Failed to add git repository");
  return res.json();
}

export async function reindexResource(
  projectId: string,
  resourceId: string
): Promise<Resource> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/resources/${resourceId}/reindex`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to reindex resource");
  return res.json();
}

// Global Resource Library Functions

// List all resources in the global library
export async function listGlobalResources(
  skip: number = 0,
  limit: number = 100,
  status?: "pending" | "indexing" | "ready" | "failed"
): Promise<GlobalResource[]> {
  const params = new URLSearchParams();
  params.set("skip", skip.toString());
  params.set("limit", limit.toString());
  if (status) params.set("status", status);

  const res = await fetchWithAuth(`${API_BASE}/resources?${params.toString()}`);
  if (!res.ok) throw new Error("Failed to fetch global resources");
  return res.json();
}

// Get a specific resource from the global library
export async function getGlobalResource(resourceId: string): Promise<GlobalResource> {
  const res = await fetchWithAuth(`${API_BASE}/resources/${resourceId}`);
  if (!res.ok) throw new Error("Failed to fetch resource");
  return res.json();
}

// Link an existing resource from the library to a project
export async function linkResourceToProject(
  projectId: string,
  resourceId: string
): Promise<Resource> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/resources/link`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resource_id: resourceId }),
  });
  if (!res.ok) {
    if (res.status === 409) {
      throw new Error("Resource is already linked to this project");
    }
    throw new Error("Failed to link resource to project");
  }
  return res.json();
}

// Unlink a resource from a project (does not delete the resource)
export async function unlinkResourceFromProject(
  projectId: string,
  resourceId: string
): Promise<UnlinkResponse> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/resources/${resourceId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to unlink resource from project");
  return res.json();
}

// Permanently delete a resource from the global library
export async function deleteGlobalResource(resourceId: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/resources/${resourceId}`, {
    method: "DELETE",
  });
  if (!res.ok) {
    if (res.status === 409) {
      throw new Error("Cannot delete: resource is still linked to projects");
    }
    throw new Error("Failed to delete resource");
  }
}

// RAG Chunk types for debugging
export interface ResourceChunk {
  id: string;
  content: string;
  source: string;
  chunk_index: number;
  metadata: {
    doc_id?: string;
    page_numbers?: string;
    page_ref?: string;
    line_start?: number;
    line_end?: number;
    char_count?: number;
    doc_type?: string;
    filename?: string;
    file_path?: string;
    github_base_url?: string;
    [key: string]: unknown;
  };
}

export interface ResourceChunksResponse {
  resource_id: string;
  namespace: string;
  total_chunks: number;
  chunks: ResourceChunk[];
}

// Get the RAG chunks for a resource (for debugging)
export async function getResourceChunks(
  resourceId: string,
  limit: number = 500
): Promise<ResourceChunksResponse> {
  const params = new URLSearchParams();
  params.set("limit", limit.toString());

  const res = await fetchWithAuth(`${API_BASE}/resources/${resourceId}/chunks?${params.toString()}`);
  if (!res.ok) {
    if (res.status === 400) {
      const error = await res.json();
      throw new Error(error.detail || "Resource is not indexed yet");
    }
    throw new Error("Failed to fetch resource chunks");
  }
  return res.json();
}

// Conversation message for context
export interface ConversationMessage {
  role: "user" | "assistant";
  content: string;
}

// Tool call event for streaming
export interface ToolCallEvent {
  id?: string;
  tool?: string;
  name?: string;
  query?: string;
  input?: Record<string, unknown>;
}

// Tool result event for streaming
export interface ToolResultEvent {
  tool?: string;
  tool_call_id?: string;
  found?: number;
  query?: string;
  result?: unknown;
}

// Finding saved event (from save_finding tool)
export interface FindingSavedEvent {
  finding_id: string;
  finding_content: string;
}

export interface UsageEvent {
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
}

// Plan event for streaming (acknowledgment from router)
export interface PlanEvent {
  category: string;
  acknowledgment: string;
  complexity: string;
  search_strategy: string;
}

// Query (non-streaming)
export async function queryThread(
  projectId: string,
  threadId: string,
  question: string,
  topK: number = 5
): Promise<QueryResponse> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}/query`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question, top_k: topK }),
  });
  if (!res.ok) throw new Error("Failed to query thread");
  return res.json();
}

// Streaming query
export async function queryThreadStream(
  projectId: string,
  threadId: string,
  question: string,
  onChunk: (chunk: string) => void,
  onSources: (sources: SourceInfo[]) => void,
  onDone: () => void,
  conversationHistory: ConversationMessage[] = [],
  topK: number = 5,
  onStatus?: (status: string) => void,
  onToolCall?: (event: ToolCallEvent) => void,
  onToolResult?: (event: ToolResultEvent) => void,
  onThinking?: (content: string) => void,
  onUsage?: (event: UsageEvent) => void,
  onPlan?: (event: PlanEvent) => void,
  contextOnly: boolean = false,
  onFindingSaved?: (event: FindingSavedEvent) => void
): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}/query/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      question,
      top_k: topK,
      conversation_history: conversationHistory,
      context_only: contextOnly
    }),
  });

  if (!res.ok) throw new Error("Failed to query thread");

  const reader = res.body?.getReader();
  if (!reader) throw new Error("No response body");

  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n\n");
    buffer = lines.pop() || "";

    for (const line of lines) {
      if (line.startsWith("data: ")) {
        const data = JSON.parse(line.slice(6));
        if (data.type === "plan" && onPlan) {
          onPlan({
            category: data.category,
            acknowledgment: data.acknowledgment,
            complexity: data.complexity,
            search_strategy: data.search_strategy,
          });
        } else if (data.type === "status" && onStatus) {
          onStatus(data.status);
        } else if (data.type === "tool_call" && onToolCall) {
          onToolCall({ tool: data.tool, query: data.query });
        } else if (data.type === "tool_result") {
          if (onToolResult) {
            onToolResult({ tool: data.tool, found: data.found, query: data.query });
          }
          // Trigger finding saved callback for save_finding tool
          if (data.tool === "save_finding" && data.saved && onFindingSaved) {
            onFindingSaved({
              finding_id: data.finding_id,
              finding_content: data.finding_content,
            });
          }
        } else if (data.type === "thinking" && onThinking) {
          onThinking(data.content);
        } else if (data.type === "usage" && onUsage) {
          onUsage({
            input_tokens: data.input_tokens,
            output_tokens: data.output_tokens,
            total_tokens: data.total_tokens,
          });
        } else if (data.type === "sources") {
          onSources(data.sources);
        } else if (data.type === "chunk") {
          onChunk(data.content);
        } else if (data.type === "done") {
          onDone();
        }
      }
    }
  }
}

// Resource file URL
export function getResourceFileUrl(projectId: string, resourceId: string): string {
  return `${API_BASE}/projects/${projectId}/resources/${resourceId}/file`;
}

// Messages
export interface ChildThreadInfo {
  id: string;
  title: string;
  context_text: string | null;
}

export interface ToolCallInfo {
  id: string;
  tool: string;
  query?: string | null;
  timestamp?: number | null;
  status: "running" | "complete" | "empty" | "failed";
  found?: number | null;
  duration_ms?: number | null;
}

export interface Message {
  id: string;
  thread_id: string;
  role: "user" | "assistant";
  content: string;
  sources: SourceInfo[] | null;
  tool_calls: ToolCallInfo[] | null;
  child_threads: ChildThreadInfo[] | null;
  created_at: string;
}

export async function listMessages(projectId: string, threadId: string): Promise<Message[]> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}/messages`);
  if (!res.ok) throw new Error("Failed to fetch messages");
  return res.json();
}

export async function createMessage(
  projectId: string,
  threadId: string,
  role: "user" | "assistant",
  content: string,
  sources?: SourceInfo[]
): Promise<Message> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ role, content, sources: sources || null }),
  });
  if (!res.ok) throw new Error("Failed to create message");
  return res.json();
}

export async function clearMessages(projectId: string, threadId: string): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads/${threadId}/messages`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to clear messages");
}

// Findings (Key Findings feature)
export interface Finding {
  id: string;
  project_id: string;
  thread_id: string | null;
  message_id: string | null;
  content: string;
  note: string | null;
  created_at: string;
}

export interface FindingCreate {
  content: string;
  thread_id?: string | null;
  message_id?: string | null;
  note?: string | null;
}

export async function listFindings(
  projectId: string,
  threadId?: string
): Promise<Finding[]> {
  const params = new URLSearchParams();
  if (threadId) params.set("thread_id", threadId);

  const url = `${API_BASE}/projects/${projectId}/findings${params.toString() ? `?${params.toString()}` : ""}`;
  const res = await fetchWithAuth(url);
  if (!res.ok) throw new Error("Failed to fetch findings");
  return res.json();
}

export async function createFinding(
  projectId: string,
  finding: FindingCreate
): Promise<Finding> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/findings`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(finding),
  });
  if (!res.ok) throw new Error("Failed to create finding");
  return res.json();
}

export async function updateFinding(
  projectId: string,
  findingId: string,
  updates: { note?: string }
): Promise<Finding> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/findings/${findingId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(updates),
  });
  if (!res.ok) throw new Error("Failed to update finding");
  return res.json();
}

export async function deleteFinding(
  projectId: string,
  findingId: string
): Promise<void> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/findings/${findingId}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error("Failed to delete finding");
}

export async function summarizeFindings(
  projectId: string
): Promise<{ summary: string }> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/findings/summarize`, {
    method: "POST",
  });
  if (!res.ok) throw new Error("Failed to summarize findings");
  return res.json();
}

export async function emailFindings(
  projectId: string,
  email: string,
  content?: string
): Promise<{ status: string; to: string }> {
  let url = `${API_BASE}/projects/${projectId}/findings/email?email=${encodeURIComponent(email)}`;
  if (content) {
    url += `&content=${encodeURIComponent(content)}`;
  }
  const res = await fetchWithAuth(url, { method: "POST" });
  if (!res.ok) throw new Error("Failed to send email");
  return res.json();
}

// Child thread creation (Dive Deeper)
export async function createChildThread(
  projectId: string,
  parentThreadId: string,
  parentMessageId: string,
  contextText: string,
  title?: string
): Promise<Thread> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/threads`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      title: title || null,
      parent_thread_id: parentThreadId,
      parent_message_id: parentMessageId,
      context_text: contextText,
    }),
  });
  if (!res.ok) throw new Error("Failed to create child thread");
  return res.json();
}

// Semantic search types
export interface SemanticSearchResult {
  content: string;
  source: string;
  score: number;
  snippet: string;
  resource_id?: string | null;
  page_ref?: string | null;
}

export interface SemanticSearchResponse {
  results: SemanticSearchResult[];
  query: string;
}

// Semantic search
export async function semanticSearch(
  projectId: string,
  query: string,
  topK: number = 10
): Promise<SemanticSearchResponse> {
  const res = await fetchWithAuth(`${API_BASE}/projects/${projectId}/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ query, top_k: topK }),
  });
  if (!res.ok) throw new Error("Failed to perform semantic search");
  return res.json();
}

// ============================================================================
// Conversation Jobs (Persistent Conversations)
// ============================================================================

export interface ConversationJob {
  id: string;
  thread_id: string;
  project_id: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  user_message_content: string;
  partial_response: string | null;
  sources_json: string | null;
  assistant_message_id: string | null;
  error_message: string | null;
  created_at: string;
  started_at: string | null;
  completed_at: string | null;
  token_count: number | null;
  duration_ms: number | null;
}

/**
 * Create a new conversation job.
 * This starts a background task to process the conversation.
 * Returns immediately with the job details so frontend can poll for updates.
 */
export async function createJob(
  projectId: string,
  threadId: string,
  question: string,
  contextOnly: boolean = false,
  startImmediately: boolean = false
): Promise<ConversationJob> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        question,
        context_only: contextOnly,
        start_immediately: startImmediately
      }),
    }
  );
  if (!res.ok) throw new Error("Failed to create conversation job");
  return res.json();
}

/**
 * Get job status and partial response.
 * Also updates last_polled_at to track user presence (for notification logic).
 */
export async function getJob(
  projectId: string,
  threadId: string,
  jobId: string
): Promise<ConversationJob> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/${jobId}`
  );
  if (!res.ok) throw new Error("Failed to fetch job");
  return res.json();
}

/**
 * Get the currently active (pending/running) job for a thread.
 * Returns null if there's no active job.
 */
export async function getActiveJob(
  projectId: string,
  threadId: string
): Promise<ConversationJob | null> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/active`
  );
  if (!res.ok) {
    // 404 means no active job, which is fine
    if (res.status === 404) return null;
    throw new Error("Failed to fetch active job");
  }
  const data = await res.json();
  return data;  // Can be null
}

/**
 * Active job info for a thread (minimal, for sidebar indicators).
 */
export interface ActiveThreadJob {
  thread_id: string;
  job_id: string;
  status: "pending" | "running";
}

/**
 * Get all active (pending/running) jobs for a project.
 * Used for showing indicators in the thread sidebar.
 */
export async function getProjectActiveJobs(
  projectId: string
): Promise<ActiveThreadJob[]> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/jobs/active`
  );
  if (!res.ok) {
    throw new Error("Failed to fetch active jobs");
  }
  return res.json();
}

/**
 * Callbacks for active jobs WebSocket stream.
 */
export interface ActiveJobsStreamCallbacks {
  onInitial?: (activeThreadIds: string[]) => void;
  onJobUpdate?: (threadId: string, status: string) => void;
  onError?: (error: string) => void;
  onClose?: () => void;
}

/**
 * Connect to WebSocket for real-time active jobs updates.
 * Returns a cleanup function to close the connection.
 */
export function connectToActiveJobsStream(
  projectId: string,
  callbacks: ActiveJobsStreamCallbacks
): () => void {
  const wsUrl = `${WS_BASE}/ws/projects/${projectId}/active-jobs`;
  const ws = new WebSocket(wsUrl);

  ws.onopen = () => {
    console.log(`[ActiveJobs WS] Connected to project ${projectId}`);
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      switch (data.type) {
        case "initial":
          callbacks.onInitial?.(data.data.active_thread_ids as string[]);
          break;
        case "job_update":
          callbacks.onJobUpdate?.(
            data.data.thread_id as string,
            data.data.status as string
          );
          break;
        case "error":
          callbacks.onError?.(data.data.message as string);
          break;
      }
    } catch (err) {
      console.error("[ActiveJobs WS] Failed to parse message:", err);
    }
  };

  ws.onerror = (error) => {
    console.error("[ActiveJobs WS] Error:", error);
    callbacks.onError?.("WebSocket error");
  };

  ws.onclose = () => {
    console.log("[ActiveJobs WS] Connection closed");
    callbacks.onClose?.();
  };

  // Return cleanup function
  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  };
}

/**
 * Cancel a pending or running job.
 */
export async function cancelJob(
  projectId: string,
  threadId: string,
  jobId: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/${jobId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to cancel job");
}

/**
 * Start a pending job via Celery.
 * Called when user navigates away during SSE streaming.
 */
export async function startJob(
  projectId: string,
  threadId: string,
  jobId: string
): Promise<ConversationJob> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/${jobId}/start`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to start job");
  return res.json();
}

/**
 * Update job progress (partial response) before handing off to Celery.
 * Called when user navigates away during SSE streaming.
 */
export async function updateJobProgress(
  projectId: string,
  threadId: string,
  jobId: string,
  partialResponse: string,
  sourcesJson?: string
): Promise<ConversationJob> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/${jobId}/progress`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        partial_response: partialResponse,
        sources_json: sourcesJson
      }),
    }
  );
  if (!res.ok) throw new Error("Failed to update job progress");
  return res.json();
}

/**
 * Mark a job as completed after SSE streaming finishes successfully.
 */
export async function completeJob(
  projectId: string,
  threadId: string,
  jobId: string,
  assistantMessageId: string,
  partialResponse: string,
  sourcesJson?: string,
  tokenCount?: number,
  durationMs?: number
): Promise<ConversationJob> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/threads/${threadId}/jobs/${jobId}/complete`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        assistant_message_id: assistantMessageId,
        partial_response: partialResponse,
        sources_json: sourcesJson,
        token_count: tokenCount,
        duration_ms: durationMs
      }),
    }
  );
  if (!res.ok) throw new Error("Failed to complete job");
  return res.json();
}

// ============================================================================
// Notifications
// ============================================================================

export interface Notification {
  id: string;
  project_id: string;
  thread_id: string | null;
  job_id: string | null;
  type: "job_completed" | "job_failed";
  title: string;
  body: string | null;
  read: boolean;
  created_at: string;
}

/**
 * List notifications for a project.
 */
export async function listNotifications(
  projectId: string,
  unreadOnly: boolean = false,
  limit: number = 50
): Promise<Notification[]> {
  const params = new URLSearchParams();
  if (unreadOnly) params.set("unread_only", "true");
  params.set("limit", limit.toString());

  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/notifications?${params.toString()}`
  );
  if (!res.ok) throw new Error("Failed to fetch notifications");
  return res.json();
}

/**
 * Get the count of unread notifications for a project.
 * Used to display the badge number on the notification bell.
 */
export async function getUnreadNotificationCount(
  projectId: string
): Promise<number> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/notifications/unread-count`
  );
  if (!res.ok) throw new Error("Failed to fetch unread count");
  const data = await res.json();
  return data.count;
}

/**
 * Mark a single notification as read.
 */
export async function markNotificationRead(
  projectId: string,
  notificationId: string
): Promise<Notification> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/notifications/${notificationId}`,
    { method: "PATCH" }
  );
  if (!res.ok) throw new Error("Failed to mark notification as read");
  return res.json();
}

/**
 * Mark all notifications for a project as read.
 */
export async function markAllNotificationsRead(
  projectId: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/notifications/mark-all-read`,
    { method: "POST" }
  );
  if (!res.ok) throw new Error("Failed to mark all notifications as read");
}

/**
 * Delete a notification.
 */
export async function deleteNotification(
  projectId: string,
  notificationId: string
): Promise<void> {
  const res = await fetchWithAuth(
    `${API_BASE}/projects/${projectId}/notifications/${notificationId}`,
    { method: "DELETE" }
  );
  if (!res.ok) throw new Error("Failed to delete notification");
}

// ============================================================================
// WebSocket Streaming for Jobs
// ============================================================================

export interface JobStreamEvent {
  type: "state" | "status" | "chunk" | "sources" | "thinking" | "plan" | "tool_call" | "tool_result" | "usage" | "done" | "error";
  data: Record<string, unknown>;
}

// Activity item from the server
export interface ActivityItem {
  type: "tool_call" | "tool_result";
  id?: string;
  name?: string;
  tool?: string;
  input?: Record<string, unknown>;
  result?: unknown;
  found?: number;
}

// Full state snapshot sent on WebSocket connect
export interface JobStateSnapshot {
  status: string;
  content: string;
  sources: SourceInfo[];
  acknowledgment: string;
  activity: ActivityItem[];
  thinking: string;
}

export interface JobStreamCallbacks {
  onState?: (state: JobStateSnapshot) => void;  // Full state snapshot on connect
  onStatus?: (status: string) => void;
  onChunk?: (content: string) => void;
  onSources?: (sources: SourceInfo[]) => void;
  onThinking?: (content: string) => void;
  onPlan?: (plan: PlanEvent) => void;
  onToolCall?: (toolCall: ToolCallEvent) => void;
  onToolResult?: (toolResult: ToolResultEvent) => void;
  onUsage?: (usage: UsageEvent) => void;
  onDone?: (data: { status: string; message_id: string; content: string; sources: SourceInfo[] }) => void;
  onError?: (message: string) => void;
}

/**
 * Connect to a job's WebSocket stream.
 * Returns a cleanup function to close the connection.
 */
export function connectToJobStream(
  jobId: string,
  callbacks: JobStreamCallbacks
): { close: () => void } {
  const url = `${WS_BASE}/ws/jobs/${jobId}`;
  const ws = new WebSocket(url);

  ws.onopen = () => {
    console.log(`[WS] Connected to job ${jobId}`);
  };

  ws.onmessage = (event) => {
    try {
      const data: JobStreamEvent = JSON.parse(event.data);

      switch (data.type) {
        case "state":
          callbacks.onState?.(data.data as unknown as JobStateSnapshot);
          break;
        case "status":
          callbacks.onStatus?.(data.data.status as string);
          break;
        case "chunk":
          callbacks.onChunk?.(data.data.content as string);
          break;
        case "sources":
          callbacks.onSources?.(data.data.sources as SourceInfo[]);
          break;
        case "thinking":
          callbacks.onThinking?.(data.data.content as string);
          break;
        case "plan":
          callbacks.onPlan?.(data.data as unknown as PlanEvent);
          break;
        case "tool_call":
          callbacks.onToolCall?.(data.data as unknown as ToolCallEvent);
          break;
        case "tool_result":
          callbacks.onToolResult?.(data.data as unknown as ToolResultEvent);
          break;
        case "usage":
          callbacks.onUsage?.(data.data as unknown as UsageEvent);
          break;
        case "done":
          callbacks.onDone?.(data.data as { status: string; message_id: string; content: string; sources: SourceInfo[] });
          break;
        case "error":
          callbacks.onError?.(data.data.message as string);
          break;
      }
    } catch (e) {
      console.error("[WS] Failed to parse message:", e);
    }
  };

  ws.onerror = (error) => {
    console.error("[WS] Error:", error);
    callbacks.onError?.("WebSocket connection error");
  };

  ws.onclose = () => {
    console.log(`[WS] Disconnected from job ${jobId}`);
  };

  return {
    close: () => {
      if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
        ws.close();
      }
    }
  };
}
