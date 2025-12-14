/**
 * App-Level WebSocket Manager
 *
 * A singleton that manages a single persistent WebSocket connection for the entire app session.
 * Never disconnects during navigation - stays connected across projects and threads.
 *
 * Features:
 * - Single connection for entire session
 * - Auto-reconnect with exponential backoff
 * - Message-based thread subscription (includes project_id)
 * - Callbacks for active jobs, job updates, and job events
 */

export interface JobInfo {
  project_id: string;
  thread_id: string;
  job_id: string;
  status: string;
}

export interface JobEvent {
  type: string;
  job_id?: string;
  thread_id?: string;
  // Plan event fields
  acknowledgment?: string;
  // Tool event fields
  tool?: string;
  query?: string;
  found?: number;
  // Chunk event fields
  content?: string;
  // Status event fields
  status?: string;
  // Error event fields
  message?: string;
  // Sources event fields
  sources?: unknown[];
  // Usage event fields
  total_tokens?: number;
}

export interface ActivityItem {
  id: string;
  type: "tool_call" | "tool_result" | "phase_change";
  timestamp: number;
  // For tool calls and results:
  name?: string;
  tool?: string;  // Tool name
  query?: string; // Search query or resource name for display
  input?: Record<string, unknown>;
  // For tool results:
  tool_call_id?: string;
  found?: number;
  // For phase changes:
  phase?: string;
  action?: string;
}

export interface JobState {
  project_id: string;
  thread_id: string;
  job_id: string | null;
  status: string;
  // Current phase and action (what agent is doing NOW)
  current_phase: "idle" | "initializing" | "planning" | "searching" | "thinking" | "responding" | "done";
  current_action: string;
  // Accumulated output
  content: string;
  sources: unknown[];
  thinking: string;
  // Full activity history
  activity: ActivityItem[];
  // Timing
  started_at: string;
  // Backwards compat
  acknowledgment?: string;
}

export interface AppWSCallbacks {
  onActiveJobs?: (jobs: JobInfo[]) => void;
  onJobUpdate?: (job: JobInfo) => void;
  onJobState?: (state: JobState) => void;
  onJobEvent?: (event: JobEvent) => void;
  onConnectionChange?: (connected: boolean) => void;
}

class AppWebSocketManager {
  private ws: WebSocket | null = null;
  private subscribedProjectId: string | null = null;
  private subscribedThreadId: string | null = null;
  private callbacks: AppWSCallbacks = {};

  // Reconnection state
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 15;
  private baseDelay = 1000; // 1 second
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;
  private isConnecting = false;

  /**
   * Connect to the app-level WebSocket.
   * Should be called once when the app loads.
   */
  connect(): void {
    // If already connected or connecting, do nothing
    if (this.ws?.readyState === WebSocket.OPEN || this.isConnecting) {
      return;
    }

    this.intentionalClose = false;
    this.createConnection();
  }

  /**
   * Disconnect from the WebSocket.
   * Should only be called when the app is unloading.
   */
  disconnect(): void {
    this.intentionalClose = true;

    if (this.reconnectTimeout) {
      clearTimeout(this.reconnectTimeout);
      this.reconnectTimeout = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }

    this.subscribedProjectId = null;
    this.subscribedThreadId = null;
    this.reconnectAttempts = 0;
    this.isConnecting = false;
    this.callbacks.onConnectionChange?.(false);
  }

  /**
   * Subscribe to a thread's job events.
   * Automatically unsubscribes from any previous thread.
   */
  subscribeThread(projectId: string, threadId: string): void {
    // Store for re-subscription after reconnect
    this.subscribedProjectId = projectId;
    this.subscribedThreadId = threadId;

    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Will subscribe after connection
      return;
    }

    this.ws.send(JSON.stringify({
      type: "subscribe_thread",
      project_id: projectId,
      thread_id: threadId,
    }));
  }

  /**
   * Unsubscribe from the current thread's job events.
   */
  unsubscribeThread(): void {
    this.subscribedProjectId = null;
    this.subscribedThreadId = null;

    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      return;
    }

    this.ws.send(JSON.stringify({
      type: "unsubscribe_thread",
    }));
  }

  /**
   * Set callbacks for WebSocket events.
   */
  setCallbacks(callbacks: AppWSCallbacks): void {
    this.callbacks = callbacks;
  }

  /**
   * Clear all callbacks.
   */
  clearCallbacks(): void {
    this.callbacks = {};
  }

  /**
   * Get current connection status.
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Get the currently subscribed thread ID.
   */
  getSubscribedThreadId(): string | null {
    return this.subscribedThreadId;
  }

  /**
   * Get the currently subscribed project ID.
   */
  getSubscribedProjectId(): string | null {
    return this.subscribedProjectId;
  }

  private createConnection(): void {
    if (this.isConnecting) return;
    this.isConnecting = true;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || "localhost:8000";
    const wsUrl = `${protocol}//${host}/ws/app`;

    console.log("[AppWS] Connecting to:", wsUrl);

    try {
      this.ws = new WebSocket(wsUrl);
      this.setupEventHandlers();
    } catch (error) {
      console.error("[AppWS] Failed to create WebSocket:", error);
      this.isConnecting = false;
      this.scheduleReconnect();
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log("[AppWS] Connected");
      this.isConnecting = false;
      this.reconnectAttempts = 0;
      this.callbacks.onConnectionChange?.(true);

      // Re-subscribe to thread if we had one
      if (this.subscribedProjectId && this.subscribedThreadId) {
        this.subscribeThread(this.subscribedProjectId, this.subscribedThreadId);
      }
    };

    this.ws.onclose = (event) => {
      console.log("[AppWS] Connection closed:", event.code, event.reason);
      this.isConnecting = false;
      this.callbacks.onConnectionChange?.(false);

      // Only reconnect if not intentionally closed
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error("[AppWS] WebSocket error:", error);
      this.isConnecting = false;
    };

    this.ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        this.handleMessage(message);
      } catch (error) {
        console.error("[AppWS] Failed to parse message:", error);
      }
    };
  }

  private handleMessage(message: { type: string; data: Record<string, unknown> }): void {
    switch (message.type) {
      case "active_jobs": {
        // Initial list of all active jobs across all projects
        const jobs = (message.data?.jobs as JobInfo[]) || [];
        this.callbacks.onActiveJobs?.(jobs);
        break;
      }

      case "job_update": {
        // Job status changed (for sidebar indicators)
        const jobInfo = message.data as unknown as JobInfo;
        if (jobInfo.project_id && jobInfo.thread_id) {
          this.callbacks.onJobUpdate?.(jobInfo);
        }
        break;
      }

      case "job_state": {
        // Full job state snapshot (when subscribing to thread)
        this.callbacks.onJobState?.(message.data as unknown as JobState);
        break;
      }

      case "job_event": {
        // Job event for subscribed thread (chunk, tool_call, done, etc.)
        const eventData = message.data as unknown as JobEvent;
        if (eventData) {
          this.callbacks.onJobEvent?.(eventData);
        }
        break;
      }

      case "error":
        console.error("[AppWS] Server error:", message.data);
        break;

      default:
        console.log("[AppWS] Unknown message type:", message.type);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("[AppWS] Max reconnect attempts reached");
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, ... up to 30s
    const delay = Math.min(
      this.baseDelay * Math.pow(2, this.reconnectAttempts),
      30000
    );

    console.log(`[AppWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      this.createConnection();
    }, delay);
  }
}

// Export singleton instance
export const appWS = new AppWebSocketManager();
