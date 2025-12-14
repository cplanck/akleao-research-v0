"use client";

import { createContext, useContext, useState, useCallback, useEffect, useMemo, useRef, ReactNode } from "react";
import {
  Project,
  ProjectDetail,
  Thread,
  Message,
  listProjects,
  getProject,
  createProject,
  deleteProject,
  updateProject,
  createThread,
  deleteThread,
  listMessages,
} from "@/lib/api";
import { useAppWebSocket } from "@/contexts/app-websocket-context";
import { JobEvent, JobState } from "@/lib/app-websocket";

interface ProjectContextType {
  // Projects list
  projects: Project[];
  projectsLoading: boolean;
  projectDetailLoading: boolean;  // True when loading a specific project

  // Selected project
  selectedProject: ProjectDetail | null;
  selectedThread: Thread | null;

  // Actions
  fetchProjects: () => Promise<Project[]>;
  fetchProjectDetail: (id: string, selectLastThread?: boolean) => Promise<ProjectDetail | null>;
  selectThread: (threadId: string) => void;
  handleCreateProject: (name: string) => Promise<{ project: Project; thread: Thread } | null>;
  handleDeleteProject: (id: string) => Promise<void>;
  handleCreateThread: () => Promise<Thread | null>;
  handleDeleteThread: (threadId: string) => Promise<void>;
  handleNavigateToThread: (thread: Thread) => void;
  handleThreadTitleGenerated: (newTitle: string) => void;
  handleRulesChange: (newRules: string[]) => Promise<void>;

  // UI State
  animatingThreadId: string | null;
  setAnimatingThreadId: (id: string | null) => void;
  findingsRefreshTrigger: number;
  triggerFindingsRefresh: () => void;

  // WebSocket State (from app-level WebSocket)
  activeThreadIds: Set<string>;
  wsConnected: boolean;
  currentJobState: JobState | null;
  currentJobEvent: JobEvent | null;
  subscribeToThread: (projectId: string, threadId: string) => void;

  // Utility
  buildAncestorChain: (thread: Thread | null) => Array<{id: string; title: string}>;
  parseRules: (instructions: string | null) => string[];

  // Message cache (for faster thread switching)
  getCachedMessages: (threadId: string) => Message[] | null;
  setCachedMessages: (threadId: string, messages: Message[]) => void;
  invalidateMessageCache: (threadId: string) => void;
  prefetchMessages: (projectId: string, threadId: string) => void;
}

const ProjectContext = createContext<ProjectContextType | null>(null);

// Helper to parse rules from system_instructions
function parseRules(instructions: string | null): string[] {
  if (!instructions) return [];
  try {
    const parsed = JSON.parse(instructions);
    if (Array.isArray(parsed)) return parsed;
  } catch {
    return instructions.split("\n").filter(r => r.trim());
  }
  return [];
}

// Helper to serialize rules for storage
function serializeRules(rules: string[]): string {
  return JSON.stringify(rules);
}

export function ProjectProvider({
  children,
  initialProjectId,
  initialThreadId,
}: {
  children: ReactNode;
  initialProjectId?: string;
  initialThreadId?: string;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<ProjectDetail | null>(null);
  const [selectedThread, setSelectedThread] = useState<Thread | null>(null);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectDetailLoading, setProjectDetailLoading] = useState(!!initialProjectId);  // True if we have an initial project to load
  const [animatingThreadId, setAnimatingThreadId] = useState<string | null>(null);
  const [findingsRefreshTrigger, setFindingsRefreshTrigger] = useState(0);

  // Message cache for faster thread switching
  // Map<threadId, Message[]>
  const messageCacheRef = useRef<Map<string, Message[]>>(new Map());

  // Get WebSocket state from app-level context
  const {
    wsConnected,
    activeJobs,
    currentJobState,
    currentJobEvent,
    subscribeToThread: appSubscribeToThread,
    hasActiveJob,
  } = useAppWebSocket();

  // Convert activeJobs map to activeThreadIds set for current project
  const activeThreadIds = useMemo(() => {
    if (!selectedProject) return new Set<string>();
    return activeJobs.get(selectedProject.id) ?? new Set<string>();
  }, [activeJobs, selectedProject]);

  const fetchProjects = useCallback(async () => {
    try {
      const data = await listProjects();
      setProjects(data);
      return data;
    } catch (error) {
      console.error("Failed to fetch projects:", error);
      return [];
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  const fetchProjectDetail = useCallback(async (id: string, selectLastThread: boolean = true) => {
    try {
      const data = await getProject(id);
      setSelectedProject(data);
      if (selectLastThread) {
        if (data.last_thread_id) {
          const thread = data.threads.find(t => t.id === data.last_thread_id);
          if (thread) setSelectedThread(thread);
          else if (data.threads.length > 0) setSelectedThread(data.threads[0]);
          else setSelectedThread(null);
        } else if (data.threads.length > 0) {
          setSelectedThread(data.threads[0]);
        } else {
          setSelectedThread(null);
        }
      }
      return data;
    } catch (error) {
      console.error("Failed to fetch project:", error);
      return null;
    }
  }, []);

  const selectThread = useCallback((threadId: string) => {
    if (!selectedProject) return;
    const thread = selectedProject.threads.find(t => t.id === threadId);
    if (thread) {
      setSelectedThread(thread);
    }
  }, [selectedProject]);

  const handleCreateProject = useCallback(async (name: string) => {
    try {
      const project = await createProject(name);
      // Automatically create first thread
      const thread = await createThread(project.id);
      await fetchProjects();
      const detail = await getProject(project.id);
      setSelectedProject(detail);
      setSelectedThread(thread);
      return { project, thread };
    } catch (error) {
      console.error("Failed to create project:", error);
      return null;
    }
  }, [fetchProjects]);

  const handleDeleteProject = useCallback(async (id: string) => {
    try {
      await deleteProject(id);
      if (selectedProject?.id === id) {
        setSelectedProject(null);
        setSelectedThread(null);
      }
      await fetchProjects();
    } catch (error) {
      console.error("Failed to delete project:", error);
    }
  }, [selectedProject, fetchProjects]);

  const handleCreateThread = useCallback(async () => {
    if (!selectedProject) return null;
    try {
      const thread = await createThread(selectedProject.id);
      await fetchProjectDetail(selectedProject.id, false);
      setSelectedThread(thread);
      return thread;
    } catch (error) {
      console.error("Failed to create thread:", error);
      return null;
    }
  }, [selectedProject, fetchProjectDetail]);

  const handleDeleteThread = useCallback(async (threadId: string) => {
    if (!selectedProject) return;
    try {
      await deleteThread(selectedProject.id, threadId);
      if (selectedThread?.id === threadId) {
        setSelectedThread(null);
      }
      await fetchProjectDetail(selectedProject.id, false);
    } catch (error) {
      console.error("Failed to delete thread:", error);
    }
  }, [selectedProject, selectedThread, fetchProjectDetail]);

  const handleNavigateToThread = useCallback((thread: Thread) => {
    if (!selectedProject) return;
    const existingThread = selectedProject.threads.find(t => t.id === thread.id);
    if (!existingThread) {
      setSelectedProject({
        ...selectedProject,
        threads: [thread, ...selectedProject.threads],
      });
    }
    setSelectedThread(thread);
  }, [selectedProject]);

  const handleThreadTitleGenerated = useCallback((newTitle: string) => {
    if (selectedThread && selectedProject) {
      const updatedThread = { ...selectedThread, title: newTitle };
      setSelectedThread(updatedThread);
      setSelectedProject({
        ...selectedProject,
        threads: selectedProject.threads.map(t =>
          t.id === selectedThread.id ? { ...t, title: newTitle } : t
        ),
      });
      setAnimatingThreadId(selectedThread.id);
    }
  }, [selectedThread, selectedProject]);

  const handleRulesChange = useCallback(async (newRules: string[]) => {
    if (!selectedProject) return;
    try {
      await updateProject(selectedProject.id, {
        system_instructions: serializeRules(newRules),
      });
      await fetchProjectDetail(selectedProject.id, false);
    } catch (error) {
      console.error("Failed to save rules:", error);
    }
  }, [selectedProject, fetchProjectDetail]);

  const buildAncestorChain = useCallback((thread: Thread | null): Array<{id: string; title: string}> => {
    if (!thread || !selectedProject) return [];
    const ancestors: Array<{id: string; title: string}> = [];
    let current = thread;

    while (current.parent_thread_id) {
      const parent = selectedProject.threads.find(t => t.id === current.parent_thread_id);
      if (!parent) break;
      ancestors.unshift({ id: parent.id, title: parent.title });
      current = parent;
    }

    return ancestors;
  }, [selectedProject]);

  const triggerFindingsRefresh = useCallback(() => {
    setFindingsRefreshTrigger(t => t + 1);
  }, []);

  // Subscribe to a thread's job events via app-level WebSocket
  const subscribeToThread = useCallback((projectId: string, threadId: string) => {
    appSubscribeToThread(projectId, threadId);
  }, [appSubscribeToThread]);

  // Message cache functions
  const getCachedMessages = useCallback((threadId: string): Message[] | null => {
    // Don't return cache if thread has an active job (need real-time streaming)
    if (hasActiveJob(selectedProject?.id || "", threadId)) {
      return null;
    }
    return messageCacheRef.current.get(threadId) || null;
  }, [selectedProject?.id, hasActiveJob]);

  const setCachedMessages = useCallback((threadId: string, messages: Message[]) => {
    messageCacheRef.current.set(threadId, messages);
  }, []);

  const invalidateMessageCache = useCallback((threadId: string) => {
    messageCacheRef.current.delete(threadId);
  }, []);

  const prefetchMessages = useCallback((projectId: string, threadId: string) => {
    // Don't prefetch if already cached or has active job
    if (messageCacheRef.current.has(threadId)) return;
    if (hasActiveJob(projectId, threadId)) return;

    // Fetch in background, don't await
    listMessages(projectId, threadId)
      .then((msgs) => {
        // Only cache if thread still doesn't have an active job
        if (!hasActiveJob(projectId, threadId)) {
          messageCacheRef.current.set(threadId, msgs);
        }
      })
      .catch((err) => {
        console.error("Failed to prefetch messages:", err);
      });
  }, [hasActiveJob]);

  // Invalidate cache when a job completes on a thread
  useEffect(() => {
    if (!currentJobEvent) return;
    if (currentJobEvent.type === "done" && currentJobEvent.thread_id) {
      invalidateMessageCache(currentJobEvent.thread_id);
    }
  }, [currentJobEvent, invalidateMessageCache]);

  // Initialize with URL params if provided
  useEffect(() => {
    const init = async () => {
      // Fetch projects and project detail in parallel if we have an initial project
      const projectsPromise = fetchProjects();

      if (initialProjectId) {
        // Fetch both in parallel
        const [, projectDetail] = await Promise.all([
          projectsPromise,
          fetchProjectDetail(initialProjectId, !initialThreadId),
        ]);

        // Select thread directly from returned data (don't rely on state which is async)
        if (initialThreadId && projectDetail) {
          const thread = projectDetail.threads.find(t => t.id === initialThreadId);
          if (thread) {
            setSelectedThread(thread);
          }
        }
        setProjectDetailLoading(false);
      } else {
        await projectsPromise;
        // No initial project specified, don't auto-select
        // This allows the project picker to show
      }
    };
    init();
  }, [initialProjectId, initialThreadId]);

  // Poll for resource status updates
  useEffect(() => {
    if (!selectedProject) return;

    const hasProcessing = selectedProject.resources.some(
      (r) => r.status === "pending" || r.status === "indexing"
    );

    if (hasProcessing) {
      const interval = setInterval(() => {
        fetchProjectDetail(selectedProject.id, false);
      }, 2000);
      return () => clearInterval(interval);
    }
  }, [selectedProject, fetchProjectDetail]);

  return (
    <ProjectContext.Provider value={{
      projects,
      projectsLoading,
      projectDetailLoading,
      selectedProject,
      selectedThread,
      fetchProjects,
      fetchProjectDetail,
      selectThread,
      handleCreateProject,
      handleDeleteProject,
      handleCreateThread,
      handleDeleteThread,
      handleNavigateToThread,
      handleThreadTitleGenerated,
      handleRulesChange,
      animatingThreadId,
      setAnimatingThreadId,
      findingsRefreshTrigger,
      triggerFindingsRefresh,
      activeThreadIds,
      wsConnected,
      currentJobState,
      currentJobEvent,
      subscribeToThread,
      buildAncestorChain,
      parseRules,
      getCachedMessages,
      setCachedMessages,
      invalidateMessageCache,
      prefetchMessages,
    }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const context = useContext(ProjectContext);
  if (!context) {
    throw new Error("useProject must be used within a ProjectProvider");
  }
  return context;
}
