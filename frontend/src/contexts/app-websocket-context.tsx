"use client";

import { createContext, useContext, useState, useEffect, useRef, useCallback, ReactNode } from "react";
import { appWS, JobInfo, JobEvent, JobState } from "@/lib/app-websocket";

interface AppWebSocketContextType {
  // Connection state
  wsConnected: boolean;

  // Active jobs across all projects (for sidebar indicators)
  activeJobs: Map<string, Set<string>>; // Map<projectId, Set<threadId>>

  // Current job state (for subscribed thread)
  currentJobState: JobState | null;
  currentJobEvent: JobEvent | null;

  // Actions
  subscribeToThread: (projectId: string, threadId: string) => void;
  unsubscribeFromThread: () => void;

  // Check if a thread has an active job
  hasActiveJob: (projectId: string, threadId: string) => boolean;
}

const AppWebSocketContext = createContext<AppWebSocketContextType | null>(null);

export function AppWebSocketProvider({ children }: { children: ReactNode }) {
  const [wsConnected, setWsConnected] = useState(false);
  const [activeJobs, setActiveJobs] = useState<Map<string, Set<string>>>(new Map());
  const [currentJobState, setCurrentJobState] = useState<JobState | null>(null);
  const [currentJobEvent, setCurrentJobEvent] = useState<JobEvent | null>(null);

  // Track if we've set up callbacks
  const callbacksSetup = useRef(false);

  // Subscribe to a thread's job events
  const subscribeToThread = useCallback((projectId: string, threadId: string) => {
    appWS.subscribeThread(projectId, threadId);
  }, []);

  // Unsubscribe from current thread
  const unsubscribeFromThread = useCallback(() => {
    appWS.unsubscribeThread();
    setCurrentJobState(null);
    setCurrentJobEvent(null);
  }, []);

  // Check if a thread has an active job
  const hasActiveJob = useCallback((projectId: string, threadId: string): boolean => {
    const projectThreads = activeJobs.get(projectId);
    return projectThreads?.has(threadId) ?? false;
  }, [activeJobs]);

  // Set up WebSocket connection and callbacks
  useEffect(() => {
    if (callbacksSetup.current) return;
    callbacksSetup.current = true;

    appWS.setCallbacks({
      onActiveJobs: (jobs: JobInfo[]) => {
        // Build map of active jobs by project
        const newActiveJobs = new Map<string, Set<string>>();
        for (const job of jobs) {
          if (!newActiveJobs.has(job.project_id)) {
            newActiveJobs.set(job.project_id, new Set());
          }
          newActiveJobs.get(job.project_id)!.add(job.thread_id);
        }
        setActiveJobs(newActiveJobs);
      },

      onJobUpdate: (job: JobInfo) => {
        setActiveJobs(prev => {
          const next = new Map(prev);
          const isActive = job.status === "running" || job.status === "pending";

          if (isActive) {
            // Add to active jobs
            if (!next.has(job.project_id)) {
              next.set(job.project_id, new Set());
            }
            next.get(job.project_id)!.add(job.thread_id);
          } else {
            // Remove from active jobs
            const projectThreads = next.get(job.project_id);
            if (projectThreads) {
              projectThreads.delete(job.thread_id);
              if (projectThreads.size === 0) {
                next.delete(job.project_id);
              }
            }
          }

          return next;
        });
      },

      onJobState: (state: JobState) => {
        console.log("[AppWSContext] Job state received:", state);
        setCurrentJobState(state);
      },

      onJobEvent: (event: JobEvent) => {
        console.log("[AppWSContext] Job event received:", event);
        setCurrentJobEvent(event);

        // Get job/thread IDs from event (fields are directly on event, not nested in .data)
        const eventJobId = event.job_id;
        const eventThreadId = event.thread_id;

        // Update currentJobState's activity array for tool_call and tool_result events
        // This keeps the activity log live without waiting for full state snapshots
        if (event.type === "tool_call" || event.type === "tool_result") {
          setCurrentJobState(prev => {
            if (!prev) return prev;
            // Verify this event is for the current job
            if (eventJobId && eventJobId !== prev.job_id) return prev;

            const activityItem = {
              id: `${event.type}-${Date.now()}`,
              type: event.type as "tool_call" | "tool_result",
              timestamp: Date.now(),
              // Tool name - used for both tool_call and tool_result
              name: event.tool,
              tool: event.tool,
              query: event.query,  // Search query or resource name
              found: event.found,
            };

            return {
              ...prev,
              activity: [...(prev.activity || []), activityItem],
              // Update phase based on event type
              current_phase: event.type === "tool_call" ? "searching" : prev.current_phase,
            };
          });
        }

        // Update phase and action for plan/acknowledgment events
        if (event.type === "plan" && event.acknowledgment) {
          setCurrentJobState(prev => {
            if (!prev) return prev;
            return {
              ...prev,
              current_phase: "planning",
              current_action: event.acknowledgment || "",
              acknowledgment: event.acknowledgment || "",  // Store acknowledgment for UI display
            };
          });
        }

        // Update phase when chunks start streaming
        if (event.type === "chunk") {
          setCurrentJobState(prev => {
            if (!prev) return prev;
            if (prev.current_phase !== "responding") {
              return {
                ...prev,
                current_phase: "responding",
                current_action: "",
              };
            }
            return prev;
          });
        }

        // Initialize job state when status becomes "running" (if not already set)
        if (event.type === "status" && event.status === "running") {
          setCurrentJobState(prev => {
            // If we already have state for this job, keep it
            if (prev && prev.job_id === eventJobId) return prev;

            // Create initial state for the new job
            return {
              project_id: "",  // Will be filled in by job_state message
              thread_id: eventThreadId || "",
              job_id: eventJobId || null,
              status: "running",
              current_phase: "initializing",
              current_action: "",
              content: "",
              sources: [],
              thinking: "",
              activity: [],
              started_at: new Date().toISOString(),
            };
          });
        }
      },

      onConnectionChange: (connected: boolean) => {
        setWsConnected(connected);
      },
    });

    // Connect WebSocket
    appWS.connect();

    // Cleanup on unmount (app unload)
    return () => {
      appWS.clearCallbacks();
      appWS.disconnect();
      callbacksSetup.current = false;
    };
  }, []);

  return (
    <AppWebSocketContext.Provider
      value={{
        wsConnected,
        activeJobs,
        currentJobState,
        currentJobEvent,
        subscribeToThread,
        unsubscribeFromThread,
        hasActiveJob,
      }}
    >
      {children}
    </AppWebSocketContext.Provider>
  );
}

export function useAppWebSocket() {
  const context = useContext(AppWebSocketContext);
  if (!context) {
    throw new Error("useAppWebSocket must be used within an AppWebSocketProvider");
  }
  return context;
}
