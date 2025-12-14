/**
 * Project WebSocket Manager
 *
 * A singleton that manages a single persistent WebSocket connection per project.
 * Handles thread subscription via messages (no reconnection on thread switch).
 *
 * Features:
 * - Single connection per project session
 * - Auto-reconnect with exponential backoff
 * - Message-based thread subscription
 * - Callbacks for active jobs, job updates, and job events
 */

export interface JobEvent {
  type: string;
  data: Record<string, unknown>;
}

export interface JobState {
  job_id: string | null;
  thread_id: string;
  status: string;
  content?: string;
  sources?: unknown[];
  acknowledgment?: string;
  activity?: unknown[];
  thinking?: string;
}

export interface ProjectWSCallbacks {
  onActiveJobs?: (threadIds: string[]) => void;
  onJobUpdate?: (threadId: string, status: string) => void;
  onJobState?: (state: JobState) => void;
  onJobEvent?: (event: JobEvent) => void;
  onConnectionChange?: (connected: boolean) => void;
}

class ProjectWebSocketManager {
  private ws: WebSocket | null = null;
  private projectId: string | null = null;
  private subscribedThreadId: string | null = null;
  private callbacks: ProjectWSCallbacks = {};

  // Reconnection state
  private reconnectAttempts = 0;
  private maxReconnectAttempts = 10;
  private baseDelay = 1000; // 1 second
  private reconnectTimeout: ReturnType<typeof setTimeout> | null = null;
  private intentionalClose = false;

  /**
   * Connect to the WebSocket for a project.
   * If already connected to a different project, disconnects first.
   */
  connect(projectId: string): void {
    // If already connected to this project, do nothing
    if (this.projectId === projectId && this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    // Disconnect from any existing connection
    if (this.ws) {
      this.intentionalClose = true;
      this.disconnect();
    }

    this.projectId = projectId;
    this.intentionalClose = false;
    this.createConnection();
  }

  /**
   * Disconnect from the current project WebSocket.
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

    this.projectId = null;
    this.subscribedThreadId = null;
    this.reconnectAttempts = 0;
    this.callbacks.onConnectionChange?.(false);
  }

  /**
   * Subscribe to a thread's job events.
   * Automatically unsubscribes from any previous thread.
   */
  subscribeThread(threadId: string): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      // Store the thread ID so we can subscribe after connection
      this.subscribedThreadId = threadId;
      return;
    }

    this.subscribedThreadId = threadId;
    this.ws.send(JSON.stringify({
      type: "subscribe_thread",
      thread_id: threadId,
    }));
  }

  /**
   * Unsubscribe from the current thread's job events.
   */
  unsubscribeThread(): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) {
      this.subscribedThreadId = null;
      return;
    }

    this.subscribedThreadId = null;
    this.ws.send(JSON.stringify({
      type: "unsubscribe_thread",
    }));
  }

  /**
   * Set callbacks for WebSocket events.
   */
  setCallbacks(callbacks: ProjectWSCallbacks): void {
    this.callbacks = callbacks;
  }

  /**
   * Clear all callbacks. Use when component unmounts to prevent stale updates.
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

  private createConnection(): void {
    if (!this.projectId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const host = process.env.NEXT_PUBLIC_API_URL?.replace(/^https?:\/\//, "") || "localhost:8000";
    const wsUrl = `${protocol}//${host}/ws/projects/${this.projectId}`;

    try {
      this.ws = new WebSocket(wsUrl);
      this.setupEventHandlers();
    } catch (error) {
      console.error("[ProjectWS] Failed to create WebSocket:", error);
      this.scheduleReconnect();
    }
  }

  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      console.log("[ProjectWS] Connected to project:", this.projectId);
      this.reconnectAttempts = 0;
      this.callbacks.onConnectionChange?.(true);

      // Re-subscribe to thread if we had one
      if (this.subscribedThreadId) {
        this.subscribeThread(this.subscribedThreadId);
      }
    };

    this.ws.onclose = (event) => {
      console.log("[ProjectWS] Connection closed:", event.code, event.reason);
      this.callbacks.onConnectionChange?.(false);

      // Only reconnect if not intentionally closed
      if (!this.intentionalClose) {
        this.scheduleReconnect();
      }
    };

    this.ws.onerror = (error) => {
      console.error("[ProjectWS] WebSocket error:", error);
    };

    this.ws.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data);
        this.handleMessage(message);
      } catch (error) {
        console.error("[ProjectWS] Failed to parse message:", error);
      }
    };
  }

  private handleMessage(message: { type: string; data: Record<string, unknown> }): void {
    switch (message.type) {
      case "active_jobs":
        // Initial list of threads with active jobs
        const threadIds = (message.data?.thread_ids as string[]) || [];
        this.callbacks.onActiveJobs?.(threadIds);
        break;

      case "job_update":
        // Job status changed (for sidebar indicators)
        const updateData = message.data || {};
        const threadId = updateData.thread_id as string;
        const status = updateData.status as string;
        if (threadId && status) {
          this.callbacks.onJobUpdate?.(threadId, status);
        }
        break;

      case "job_state":
        // Full job state snapshot (when subscribing to thread)
        this.callbacks.onJobState?.(message.data as unknown as JobState);
        break;

      case "job_event":
        // Job event for subscribed thread (chunk, tool_call, done, etc.)
        const eventData = message.data as unknown as JobEvent;
        if (eventData) {
          this.callbacks.onJobEvent?.(eventData);
        }
        break;

      case "error":
        console.error("[ProjectWS] Server error:", message.data);
        break;

      default:
        console.log("[ProjectWS] Unknown message type:", message.type);
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error("[ProjectWS] Max reconnect attempts reached");
      return;
    }

    // Exponential backoff: 1s, 2s, 4s, 8s, ... up to 30s
    const delay = Math.min(
      this.baseDelay * Math.pow(2, this.reconnectAttempts),
      30000
    );

    console.log(`[ProjectWS] Reconnecting in ${delay}ms (attempt ${this.reconnectAttempts + 1})`);

    this.reconnectTimeout = setTimeout(() => {
      this.reconnectAttempts++;
      this.createConnection();
    }, delay);
  }
}

// Export singleton instance
export const projectWS = new ProjectWebSocketManager();
