"use client";

import { useState, useRef, useEffect, useCallback } from "react";
import dynamic from "next/dynamic";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
} from "@/components/ui/dialog";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Input } from "@/components/ui/input";
import { MarkdownContent } from "@/components/markdown-content";
import { SourceInfo, listMessages, addUrlResource, getResourceFileUrl, Resource, generateThreadTitle, createFinding, createChildThread, Thread, ChildThreadInfo, createJob, getActiveJob, startJob } from "@/lib/api";
import { TextSelectionMenu } from "@/components/text-selection-menu";
import { useProject } from "@/contexts/project-context";
import { ActivityItem } from "@/lib/app-websocket";
import { getToolConfig, formatToolStatus } from "@/lib/tool-registry";
import { toast } from "sonner";

// Dynamically import PdfViewer to avoid SSR issues
const PdfViewer = dynamic(
  () => import("@/components/pdf-viewer").then((mod) => mod.PdfViewer),
  {
    ssr: false,
    loading: () => (
      <div className="flex items-center justify-center h-full">
        <span className="text-muted-foreground">Loading PDF viewer...</span>
      </div>
    ),
  }
);

// Track what tool was used last (to know where the answer came from)
interface ToolCallRecord {
  id?: string;
  tool?: string;
  name?: string;
  query?: string | null;
  input?: Record<string, unknown>;
  found?: number | null;
  timestamp?: number | null;
  status?: "running" | "complete" | "empty" | "failed";
  result?: unknown;
  duration_ms?: number | null;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceInfo[];
  isQuestion?: boolean;
  thinking?: string;  // Extended thinking content from Claude
  toolCalls?: ToolCallRecord[];  // Tool calls made during this response
  childThreads?: ChildThreadInfo[];  // Child threads spawned from this message
}

// Minimal ancestor info for breadcrumbs
interface AncestorThreadInfo {
  id: string;
  title: string;
}

interface ChatInterfaceProps {
  projectId: string;
  threadId: string;
  threadTitle: string;
  parentThreadId?: string | null;  // For child threads - the parent thread ID
  contextText?: string | null;  // The selected text that spawned this child thread
  ancestorThreads?: AncestorThreadInfo[];  // Full ancestry chain (from root to immediate parent)
  onResourceAdded?: () => void;
  onThreadTitleGenerated?: (newTitle: string) => void;  // Callback when thread title is auto-generated
  onNavigateToThread?: (thread: Thread) => void;  // Callback to navigate to a thread (for child threads)
  resources?: Resource[];  // Available resources for viewing sources
  rules?: string[];  // Project rules for the AI
  onRulesChange?: (rules: string[]) => void;  // Callback when rules change
  isRulesDialogOpen?: boolean;  // External control for rules dialog
  onRulesDialogOpenChange?: (open: boolean) => void;  // Callback when dialog state changes
  onFindingSaved?: () => void;  // Callback when a finding is saved
}

// State for viewing a source in PDF viewer
interface ViewingSource {
  resourceId: string;
  pageNumber: number;
  filename: string;
}

// Agent phases - reflects what the agent is actually doing
type AgentPhase =
  | "initializing"    // Just started, waiting for first response
  | "planning"        // Got acknowledgment, figuring out approach
  | "searching"       // Actively searching (handled separately in UI)
  | "processing"      // Got search results, making sense of them
  | "thinking"        // Extended thinking / deep reasoning
  | "synthesizing"    // Combining information, forming response
  | "cooking"         // Been working for a while (>15s)
  | "finishing";      // About to deliver response

// Verb bins by phase - larger pools with some overlap for variety
const PHASE_VERBS: Record<AgentPhase, string[]> = {
  // Big diverse pool for initial state - this is what users see first
  initializing: [
    "Warming up", "Tuning in", "Spinning up", "Booting up",
    "Getting ready", "Firing up", "Revving up", "Gearing up",
    "Powering on", "Dialing in", "Locking in", "Zeroing in",
  ],
  planning: [
    "Sizing up", "Scoping", "Charting", "Mapping out",
    "Strategizing", "Plotting", "Scheming", "Game planning",
  ],
  searching: [], // Uses specific "Searching X" UI instead
  processing: [
    "Discombobulating", "Digesting", "Crunching", "Parsing", "Unpacking",
    "Decoding", "Untangling", "Sifting through", "Making sense of",
  ],
  thinking: [
    "Mulling", "Pondering", "Contemplating", "Reasoning",
    "Noodling", "Ruminating", "Deliberating", "Musing",
  ],
  synthesizing: [
    "Vibing", "Connecting dots", "Weaving", "Piecing together",
    "Assembling", "Crystallizing", "Distilling", "Coalescing",
  ],
  cooking: [
    "Cooking", "Brewing", "Simmering", "Marinating",
    "Stewing", "Percolating", "Slow cooking",
  ],
  finishing: [
    "Polishing", "Wrapping up", "Finalizing", "Tidying up",
    "Putting finishing touches", "Almost there",
  ],
};

// Wildcard verbs that can appear in any phase (adds unpredictability)
const WILDCARD_VERBS = [
  "Vibing", "Cooking", "Working", "Thinking", "Processing",
  "Humming along", "Chugging along", "On it",
];

// Get verb for a specific phase with some randomness
function getPhaseVerb(phase: AgentPhase, seed: number = 0): string {
  // 15% chance to use a wildcard verb for variety
  if (Math.random() < 0.15) {
    return WILDCARD_VERBS[Math.floor(Math.random() * WILDCARD_VERBS.length)];
  }

  const verbs = PHASE_VERBS[phase];
  if (!verbs || verbs.length === 0) return "Working";

  // Use seed + random offset for less predictability
  const randomOffset = Math.floor(Math.random() * verbs.length);
  const index = (seed + randomOffset) % verbs.length;
  return verbs[index];
}

// Format token count (e.g., 1234 -> "1.2k", 12345 -> "12.3k")
function formatTokenCount(count: number): string {
  if (count < 1000) return count.toString();
  return (count / 1000).toFixed(1) + "k";
}

// Format elapsed time (e.g., 5.2 -> "5.2s", 65.3 -> "1:05")
function formatElapsedTime(seconds: number): string {
  if (seconds < 60) return `${seconds.toFixed(1)}s`;
  const mins = Math.floor(seconds / 60);
  const secs = Math.floor(seconds % 60);
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

// Activity log item with timestamp for animations
interface ActivityLogItem {
  id: string;
  type: "tool_call" | "tool_result" | "thinking_start";
  name?: string;  // Tool name for tool_call events
  tool?: string;  // Tool name for tool_result events
  query?: string;
  found?: number;
  timestamp: number;
}

// Detect if a message is a clarifying question
function isQuestionMessage(content: string): boolean {
  if (!content || content.length > 500) return false;

  const trimmed = content.trim();
  // Check if it ends with a question mark
  if (!trimmed.endsWith("?")) return false;

  // Check for question patterns
  const questionPatterns = [
    /^(could you|can you|would you|do you|are you|what|which|how|where|when|why|who|is there|are there)/i,
    /clarify|specify|mean by|referring to|particular|specific/i,
  ];

  return questionPatterns.some(pattern => pattern.test(trimmed));
}


// Thinking display component - shows Claude's internal reasoning
function ThinkingDisplay({ content, isStreaming }: { content: string; isStreaming: boolean }) {
  const [isExpanded, setIsExpanded] = useState(false);

  // Only show if there's actual content (not just empty/whitespace)
  if (!content || !content.trim()) return null;

  return (
    <div className="mb-2 text-xs">
      <button
        onClick={() => setIsExpanded(!isExpanded)}
        className="flex items-center gap-1.5 text-muted-foreground/60 hover:text-muted-foreground transition-colors"
      >
        <span>
          {isStreaming ? "Thinking" : "Thought process"}
        </span>
        <span className="text-[10px] opacity-60">
          {isExpanded ? "▼" : "▶"}
        </span>
      </button>

      {isExpanded && (
        <div className="mt-1.5 ml-4 p-2 bg-violet-500/5 dark:bg-violet-400/5 border border-violet-500/20 dark:border-violet-400/20 rounded text-muted-foreground whitespace-pre-wrap max-h-[200px] overflow-y-auto">
          {content}
          {isStreaming && <span className="inline-block w-1 h-3 bg-violet-500 ml-0.5 animate-pulse" />}
        </div>
      )}
    </div>
  );
}

// Animated dots component
function AnimatedDots() {
  return (
    <span className="inline-flex gap-0.5 ml-0.5">
      <span className="w-1 h-1 bg-violet-500 dark:bg-violet-400 rounded-full animate-bounce" style={{ animationDelay: "0ms" }} />
      <span className="w-1 h-1 bg-violet-500 dark:bg-violet-400 rounded-full animate-bounce" style={{ animationDelay: "150ms" }} />
      <span className="w-1 h-1 bg-violet-500 dark:bg-violet-400 rounded-full animate-bounce" style={{ animationDelay: "300ms" }} />
    </span>
  );
}

// Claude Code-style status panel with activity log flowing upward
interface AgentStatusPanelProps {
  activityLog: ActivityLogItem[];
  isThinking: boolean;
  thinkingContent: string;
  currentAction: "idle" | "thinking" | "searching" | "responding";
  resourceNames?: string[];
  elapsedTime?: number;  // Elapsed time in seconds
  tokenCount?: number;   // Total tokens used
  acknowledgment?: string;  // Plan acknowledgment from router
  hasContent?: boolean;  // Whether we've started receiving real content
}

// Compute agent phase from current state
function computeAgentPhase(
  acknowledgment: string | undefined,
  activityLog: ActivityLogItem[],
  isThinking: boolean,
  currentAction: string,
  elapsedTime: number,
  hasContent: boolean
): AgentPhase {
  // Long-running override (>15s and still working)
  if (elapsedTime > 15 && !hasContent) {
    return "cooking";
  }

  // Extended thinking mode
  if (isThinking) {
    return "thinking";
  }

  // Check tool call status
  const lastToolCall = [...activityLog].reverse().find(a => a.type === "tool_call");
  const lastToolResult = [...activityLog].reverse().find(a => a.type === "tool_result");
  const hasActiveSearch = lastToolCall && (!lastToolResult || lastToolResult.timestamp < lastToolCall.timestamp);
  const hasCompletedSearch = lastToolResult && lastToolResult.type === "tool_result";

  // Active search in progress
  if (hasActiveSearch) {
    return "searching";
  }

  // Got search results, processing them
  if (hasCompletedSearch && !hasContent) {
    // If we've been processing results for a bit, we're synthesizing
    const timeSinceResult = Date.now() - lastToolResult.timestamp;
    if (timeSinceResult > 2000) {
      return "synthesizing";
    }
    return "processing";
  }

  // Have acknowledgment but no searches yet - planning phase
  if (acknowledgment && activityLog.length === 0) {
    return "planning";
  }

  // About to finish (have content coming)
  if (hasContent) {
    return "finishing";
  }

  // Initial state - just started
  return "initializing";
}

function AgentStatusPanel({
  activityLog,
  isThinking,
  thinkingContent,
  currentAction,
  resourceNames = [],
  elapsedTime = 0,
  tokenCount,
  acknowledgment,
  hasContent = false,
}: AgentStatusPanelProps) {
  // Compute current phase
  const phase = computeAgentPhase(
    acknowledgment,
    activityLog,
    isThinking,
    currentAction,
    elapsedTime,
    hasContent
  );

  // Track phase changes to pick new verb only when phase changes
  const [currentVerb, setCurrentVerb] = useState(() => getPhaseVerb("initializing", 0));
  const lastPhaseRef = useRef<AgentPhase>("initializing");

  useEffect(() => {
    if (phase !== lastPhaseRef.current) {
      // Phase changed - pick a new random verb for this phase
      const seed = Math.floor(Math.random() * 100);
      setCurrentVerb(getPhaseVerb(phase, seed));
      lastPhaseRef.current = phase;
    }
  }, [phase]);

  // Get current action display using tool registry
  const getCurrentActionDisplay = () => {
    const lastToolCall = [...activityLog].reverse().find(a => a.type === "tool_call");
    const lastToolResult = [...activityLog].reverse().find(a => a.type === "tool_result");

    // If we have a pending tool call (no result yet), show appropriate status
    if (lastToolCall && (!lastToolResult || lastToolResult.timestamp < lastToolCall.timestamp)) {
      const toolId = lastToolCall.tool || lastToolCall.name || "unknown";
      const config = getToolConfig(toolId);

      // For search_documents, customize with resource names if available
      let text = formatToolStatus(toolId, "in_progress", {
        query: lastToolCall.query,
        resource: lastToolCall.query?.split(":")[0],
      });

      // Override for documents to include resource name
      if (toolId === "search_documents" && resourceNames.length === 1) {
        text = `Searching ${resourceNames[0]} for '${lastToolCall.query || ""}'`.replace(" for ''", "");
      }

      return {
        type: "searching",
        icon: config.icon,
        text,
        subtext: null, // Query already included in text via formatToolStatus
      };
    }

    // If actively thinking (extended thinking mode) - show as a distinct step
    if (isThinking) {
      return {
        type: "thinking",
        icon: "◇",
        text: "Thinking",
        subtext: null,
      };
    }

    // If thinking/processing (but no acknowledgment yet) - initial state
    if ((currentAction === "thinking" || currentAction === "responding") && !acknowledgment) {
      return {
        type: "processing",
        icon: "✦",
        text: currentVerb,
        subtext: null,
      };
    }

    return null;
  };

  const action = getCurrentActionDisplay();

  // Once we have real content, hide the status panel entirely
  if (hasContent) return null;

  // Don't render if nothing to show
  if (!action && activityLog.length === 0 && !acknowledgment) return null;

  return (
    <div className="text-sm">
      {/* Acknowledgment from router - THE MAIN THING the user sees first */}
      {acknowledgment && (
        <div className="mb-3">
          <p className="text-foreground">
            {acknowledgment}
          </p>
        </div>
      )}

      {/* Activity log - shows what we're doing */}
      {activityLog.length > 0 && (
        <div className="space-y-1 mb-2 text-xs font-mono">
          {activityLog.map((item) => {
            const isRecent = Date.now() - item.timestamp < 5000;
            const opacity = isRecent ? "opacity-70" : "opacity-50";

            if (item.type === "tool_call") {
              // Show tool call in progress (only if no result yet)
              const hasResult = activityLog.some(
                a => a.type === "tool_result" && a.tool === item.name
              );
              if (hasResult) return null; // Don't show if already completed

              const toolId = item.name || item.tool || "unknown";
              const config = getToolConfig(toolId);
              const statusText = formatToolStatus(toolId, "in_progress", {
                query: item.query,
                resource: item.query?.split(":")[0],
              });

              return (
                <div
                  key={item.id}
                  className="flex items-center gap-1.5 text-muted-foreground opacity-70"
                >
                  <span className="animate-pulse text-blue-500">{config.icon}</span>
                  <span className="truncate max-w-[300px]">{statusText}</span>
                  <AnimatedDots />
                </div>
              );
            }

            if (item.type === "tool_result") {
              const toolId = item.tool || "unknown";
              const config = getToolConfig(toolId);
              const found = item.found ?? 0;
              const isSuccess = found > 0;
              const stage = isSuccess ? "complete" : "failed";

              const statusText = formatToolStatus(toolId, stage, {
                query: item.query,
                count: found,
                resource: item.query?.split(":")[0],
              });

              return (
                <div
                  key={item.id}
                  className={`flex items-center gap-1.5 text-muted-foreground ${opacity} transition-opacity duration-1000`}
                >
                  <span className={isSuccess ? "text-green-600 dark:text-green-400" : "text-yellow-600 dark:text-yellow-400"}>
                    {isSuccess ? "✓" : "○"}
                  </span>
                  <span className="truncate max-w-[300px]">{statusText}</span>
                </div>
              );
            }

            return null;
          })}
        </div>
      )}

      {/* Current action status line - searching indicator, thinking, or initial loading verb */}
      {action && (
        <div className={`flex items-center gap-2 py-1 text-xs font-mono ${
          action.type === "thinking" ? "text-muted-foreground/60" : ""
        }`}>
          <span className={action.type === "thinking" ? "" : "animate-shimmer"}>{action.icon}</span>
          <span className={`font-medium ${action.type === "thinking" ? "" : "animate-shimmer"}`}>{action.text}</span>
          {action.type !== "thinking" && <AnimatedDots />}
          {action.subtext && (
            <>
              <span className="opacity-30">|</span>
              <span className="opacity-60 truncate max-w-[200px]">{action.subtext}</span>
            </>
          )}
          {/* Elapsed time and token count */}
          {(elapsedTime !== undefined || tokenCount !== undefined) && (
            <span className="ml-auto flex items-center gap-2 opacity-60">
              {elapsedTime !== undefined && (
                <span>{formatElapsedTime(elapsedTime)}</span>
              )}
              {tokenCount !== undefined && tokenCount > 0 && (
                <>
                  <span className="opacity-40">·</span>
                  <span>{formatTokenCount(tokenCount)} tokens</span>
                </>
              )}
            </span>
          )}
        </div>
      )}

      {/* Show searching status when actively searching (tool calls in progress, no specific action) */}
      {!action && activityLog.some(a => a.type === "tool_call") && (
        <div className="flex items-center gap-2 py-1 text-xs font-mono">
          <span className="animate-shimmer">✦</span>
          <span className="font-medium animate-shimmer">{currentVerb}</span>
          <AnimatedDots />
          {(elapsedTime !== undefined || tokenCount !== undefined) && (
            <span className="ml-auto flex items-center gap-2 opacity-60">
              {elapsedTime !== undefined && (
                <span>{formatElapsedTime(elapsedTime)}</span>
              )}
              {tokenCount !== undefined && tokenCount > 0 && (
                <>
                  <span className="opacity-40">·</span>
                  <span>{formatTokenCount(tokenCount)} tokens</span>
                </>
              )}
            </span>
          )}
        </div>
      )}

    </div>
  );
}

// Custom hook to detect mobile screens
function useIsMobile(breakpoint: number = 768) {
  const [isMobile, setIsMobile] = useState(false);

  useEffect(() => {
    const checkMobile = () => setIsMobile(window.innerWidth < breakpoint);
    checkMobile();
    window.addEventListener("resize", checkMobile);
    return () => window.removeEventListener("resize", checkMobile);
  }, [breakpoint]);

  return isMobile;
}

export function ChatInterface({ projectId, threadId, threadTitle, parentThreadId, contextText, ancestorThreads = [], onResourceAdded, onThreadTitleGenerated, onNavigateToThread, resources = [], rules = [], onRulesChange, isRulesDialogOpen: externalIsRulesDialogOpen, onRulesDialogOpenChange, onFindingSaved }: ChatInterfaceProps) {
  const isMobile = useIsMobile();
  // Get WebSocket state and cache functions from context
  const { subscribeToThread, currentJobState, currentJobEvent, getCachedMessages, setCachedMessages, invalidateMessageCache } = useProject();

  // ============================================
  // STATE: What we maintain locally
  // ============================================
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [showSources, setShowSources] = useState<string | null>(null);
  const [showToolCalls, setShowToolCalls] = useState<string | null>(null);
  const [viewingSource, setViewingSource] = useState<ViewingSource | null>(null);
  const [showAgentDebug, setShowAgentDebug] = useState(false); // Toggle with Ctrl+Shift+D
  const [internalIsRulesDialogOpen, setInternalIsRulesDialogOpen] = useState(false);
  const [newRuleInput, setNewRuleInput] = useState("");
  const [contextOnly, setContextOnly] = useState(false);  // Context-only mode: only answer from documents
  const [tokenCount, setTokenCount] = useState<number>(0);    // Total tokens used

  // Use external control if provided, otherwise use internal state
  const isRulesDialogOpen = externalIsRulesDialogOpen ?? internalIsRulesDialogOpen;
  const setIsRulesDialogOpen = onRulesDialogOpenChange ?? setInternalIsRulesDialogOpen;

  // ============================================
  // REFS: For tracking during streaming
  // ============================================
  const scrollRef = useRef<HTMLDivElement>(null);
  const streamingRef = useRef<string>("");  // All accumulated content (including partial words)
  const displayedRef = useRef<string>("");  // Content shown to user (only complete words)
  const sourcesRef = useRef<SourceInfo[]>([]);
  const pendingUpdateRef = useRef<boolean>(false);  // Track if we have a pending RAF update
  const rafIdRef = useRef<number | null>(null);  // RAF handle for cleanup
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const hasGeneratedTitleRef = useRef(false);  // Track if we've generated a title for this thread
  const chatContainerRef = useRef<HTMLDivElement>(null);  // Ref for the chat container (for text selection menu)
  const currentJobIdRef = useRef<string | null>(null);  // Track current job for message updates

  // ============================================
  // DERIVED STATE: From currentJobState (agent is source of truth)
  // ============================================
  // isLoading: true when agent is active
  const isLoading = currentJobState?.thread_id === threadId &&
    (currentJobState?.status === "running" || currentJobState?.status === "pending");

  // Current message ID for the active job (derived, not ref)
  const currentMessageId = isLoading && currentJobState?.job_id
    ? `job-${currentJobState.job_id}`
    : null;

  // Elapsed time: derived from started_at
  const elapsedTime = currentJobState?.started_at
    ? (Date.now() / 1000) - parseFloat(currentJobState.started_at)
    : 0;

  // Current phase and action (what agent is doing NOW)
  const agentPhase = currentJobState?.thread_id === threadId ? currentJobState?.current_phase : "idle";
  const agentAction = currentJobState?.thread_id === threadId ? currentJobState?.current_action : "";

  // Activity history from agent
  const agentActivity = (currentJobState?.thread_id === threadId ? currentJobState?.activity : []) || [];

  // Thinking content from agent
  const agentThinking = currentJobState?.thread_id === threadId ? currentJobState?.thinking : "";
  const isThinking = agentPhase === "thinking" && !!agentThinking;

  // Get acknowledgment from job state (not current_action which gets cleared)
  const acknowledgment = currentJobState?.thread_id === threadId ? currentJobState?.acknowledgment || "" : "";
  const currentAction = agentPhase === "searching" ? "searching" :
    agentPhase === "responding" ? "responding" :
    agentPhase === "idle" || agentPhase === "done" ? "idle" : "thinking";

  // Convert agent activity to ActivityLogItem format for UI
  const activityLog: ActivityLogItem[] = agentActivity
    .filter((item): item is ActivityItem & { type: "tool_call" | "tool_result" } =>
      item.type === "tool_call" || item.type === "tool_result"
    )
    .map((item) => ({
      id: item.id,
      type: item.type as "tool_call" | "tool_result",
      name: item.name,  // For tool_call events
      tool: item.tool || item.name,  // For tool_result events (or fallback to name)
      // Query is stored directly on item, or fallback to input.query for backwards compat
      query: item.query || (item.input as { query?: string })?.query,
      found: item.found,
      timestamp: typeof item.timestamp === "number" && item.timestamp > 0
        ? (item.timestamp < 10000000000 ? item.timestamp * 1000 : item.timestamp)  // Handle both seconds and ms
        : Date.now(),
    }));

  // Handle "Dive Deeper" - create child thread and navigate to it
  const handleDiveDeeper = useCallback(async (selectedText: string) => {
    if (!onNavigateToThread) {
      toast.error("Navigation not available");
      return;
    }

    try {
      // Find the last assistant message to use as parent
      const lastAssistantMessage = [...messages].reverse().find(m => m.role === "assistant");
      const parentMessageId = lastAssistantMessage?.id;

      // Create child thread with context
      const childThread = await createChildThread(
        projectId,
        threadId,
        parentMessageId || "",
        selectedText
      );

      toast.success("Created deep-dive thread");
      onNavigateToThread(childThread);
    } catch (error) {
      console.error("Failed to create child thread:", error);
      toast.error("Failed to create thread");
    }
  }, [projectId, threadId, messages, onNavigateToThread]);

  // Handle "Save Finding" - save selected text as a finding
  const handleSaveAsFinding = useCallback(async (selectedText: string) => {
    try {
      // Find the last assistant message to associate with
      const lastAssistantMessage = [...messages].reverse().find(m => m.role === "assistant");

      await createFinding(projectId, {
        content: selectedText,
        thread_id: threadId,
        message_id: lastAssistantMessage?.id,
      });

      toast.success("Saved as finding");
      onFindingSaved?.();
    } catch (error) {
      console.error("Failed to save finding:", error);
      toast.error("Failed to save finding");
    }
  }, [projectId, threadId, messages, onFindingSaved]);

  // Keyboard shortcut to toggle debug mode (Ctrl+Shift+D)
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.ctrlKey && e.shiftKey && e.key === "D") {
        e.preventDefault();
        setShowAgentDebug(prev => !prev);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  // Find a resource by resource_id or by matching source filename
  const findResourceForSource = useCallback((source: SourceInfo): Resource | null => {
    // First try exact resource_id match
    if (source.resource_id) {
      const resource = resources.find(r => r.id === source.resource_id);
      if (resource) return resource;
    }

    // Fall back to filename matching from source path
    const sourceFilename = source.source.split("/").pop()?.toLowerCase();
    if (!sourceFilename) return null;

    // Try to find a resource with matching filename
    const resource = resources.find(r => {
      const resourceFilename = r.filename?.toLowerCase() || r.source?.split("/").pop()?.toLowerCase();
      return resourceFilename === sourceFilename;
    });

    return resource || null;
  }, [resources]);

  // Handle clicking on a source to view it
  const handleViewSource = useCallback((source: SourceInfo) => {
    // Find the resource (by resource_id or filename)
    const resource = findResourceForSource(source);
    if (!resource) return;

    // Check if it's a PDF
    const isPdf = resource.filename?.toLowerCase().endsWith(".pdf");
    if (!isPdf) return;

    // Get the first page number from the comma-separated string
    const pageNumber = source.page_numbers
      ? parseInt(source.page_numbers.split(",")[0], 10)
      : 1;

    setViewingSource({
      resourceId: resource.id,
      pageNumber: isNaN(pageNumber) ? 1 : pageNumber,
      filename: resource.filename || "Document",
    });
  }, [findResourceForSource]);

  // Track if messages have been loaded for this thread
  const [messagesLoaded, setMessagesLoaded] = useState(false);

  // Helper to transform API messages to local format
  const transformMessages = useCallback((msgs: { id: string; role: "user" | "assistant"; content: string; sources?: SourceInfo[] | null; tool_calls?: ToolCallRecord[] | null; child_threads?: ChildThreadInfo[] | null }[]) => {
    return msgs.map((m) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      sources: m.sources || undefined,
      toolCalls: m.tool_calls || undefined,
      isQuestion: m.role === "assistant" ? isQuestionMessage(m.content) : false,
      childThreads: m.child_threads || undefined,
    }));
  }, []);

  // Store cache functions in refs to avoid triggering effect re-runs
  const getCachedMessagesRef = useRef(getCachedMessages);
  const setCachedMessagesRef = useRef(setCachedMessages);
  getCachedMessagesRef.current = getCachedMessages;
  setCachedMessagesRef.current = setCachedMessages;

  // Load messages when thread changes
  useEffect(() => {
    setInput("");
    setShowSources(null);
    setShowToolCalls(null);
    hasGeneratedTitleRef.current = false;  // Reset title generation tracking
    streamingRef.current = "";
    displayedRef.current = "";
    sourcesRef.current = [];
    currentJobIdRef.current = null;

    // Focus input when thread changes (desktop only - mobile/tablet keyboard is distracting)
    // Check window width directly since isMobile state may not be updated yet
    setTimeout(() => {
      if (window.innerWidth >= 1400) {
        inputRef.current?.focus();
      }
    }, 100);

    // Check cache first for instant display (use ref to avoid dep array issues)
    const cachedMessages = getCachedMessagesRef.current(threadId);
    if (cachedMessages) {
      // Show cached messages immediately
      setMessages(transformMessages(cachedMessages));
      setMessagesLoaded(true);

      // Still fetch fresh data in background (stale-while-revalidate)
      listMessages(projectId, threadId)
        .then((msgs) => {
          setMessages(transformMessages(msgs));
          setCachedMessagesRef.current(threadId, msgs);
        })
        .catch((err) => {
          console.error("Failed to refresh messages:", err);
        });
    } else {
      // No cache - show loading state and fetch
      setMessagesLoaded(false);
      listMessages(projectId, threadId)
        .then((msgs) => {
          setMessages(transformMessages(msgs));
          setCachedMessagesRef.current(threadId, msgs);
          setMessagesLoaded(true);
        })
        .catch((err) => {
          console.error("Failed to load messages:", err);
          setMessages([]);
          setMessagesLoaded(true);
        });
    }

    // Subscribe to this thread to get agent state
    subscribeToThread(projectId, threadId);
  }, [projectId, threadId, subscribeToThread, transformMessages]);

  // Handle job state snapshots from context (when subscribing to a thread)
  // This ensures the assistant message placeholder exists for active jobs
  useEffect(() => {
    // Wait for messages to be loaded before adding job placeholder
    // This prevents race condition where listMessages overwrites our placeholder
    if (!messagesLoaded) return;
    if (!currentJobState || currentJobState.thread_id !== threadId) return;
    if (!currentJobState.job_id) return;

    const jobId = currentJobState.job_id;
    const isActive = currentJobState.status === "running" || currentJobState.status === "pending";

    if (!isActive) return;

    // Update ref for job tracking
    currentJobIdRef.current = jobId;

    // Restore accumulated content to refs
    if (currentJobState.content) {
      streamingRef.current = currentJobState.content;
    }
    if (currentJobState.sources && currentJobState.sources.length > 0) {
      sourcesRef.current = currentJobState.sources as SourceInfo[];
    }

    // Ensure the assistant message placeholder exists with current content
    setMessages((prev) => {
      const hasJobMessage = prev.some(m => m.id === `job-${jobId}`);
      if (!hasJobMessage) {
        return [...prev, {
          id: `job-${jobId}`,
          role: "assistant" as const,
          content: currentJobState.content || "",
          sources: currentJobState.sources as SourceInfo[] || [],
        }];
      }
      // Update existing message if content changed
      return prev.map(m =>
        m.id === `job-${jobId}`
          ? { ...m, content: currentJobState.content || m.content, sources: (currentJobState.sources as SourceInfo[]) || m.sources }
          : m
      );
    });
  }, [currentJobState, threadId, messagesLoaded]);

  // Handle job events from context (streaming updates)
  // Only handles chunk/sources/done/error - all other state is derived from currentJobState
  useEffect(() => {
    if (!currentJobEvent) return;

    const event = currentJobEvent;

    // Verify this event is for our thread (fields are directly on event, not nested in .data)
    const eventThreadId = event.thread_id;
    if (eventThreadId && eventThreadId !== threadId) {
      // This event is for a different thread, ignore it
      return;
    }

    // Get the current job ID we're tracking
    const currentJobId = currentJobIdRef.current;

    switch (event.type) {
      case "chunk": {
        // Only process chunks if we have an active job
        if (!currentJobId) return;

        const content = event.content || "";
        streamingRef.current += content;

        // Batch updates using requestAnimationFrame for smoother streaming
        // This prevents updating React state on every single token
        if (!pendingUpdateRef.current) {
          pendingUpdateRef.current = true;
          rafIdRef.current = requestAnimationFrame(() => {
            pendingUpdateRef.current = false;

            // Word-boundary buffering: only show complete words
            // Find the last word boundary (space, newline, or punctuation followed by space)
            const fullContent = streamingRef.current;
            let displayEnd = fullContent.length;

            // Look backwards for last word boundary
            for (let i = fullContent.length - 1; i >= 0; i--) {
              const char = fullContent[i];
              if (char === ' ' || char === '\n' || char === '\t') {
                displayEnd = i + 1;  // Include the space/newline
                break;
              }
              // Also break on punctuation that typically ends words
              if (i < fullContent.length - 1 && /[.,:;!?)\]}>]/.test(char)) {
                displayEnd = i + 1;
                break;
              }
            }

            // Only update if we have new complete words to show
            const displayContent = fullContent.substring(0, displayEnd);
            if (displayContent.length > displayedRef.current.length) {
              displayedRef.current = displayContent;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === `job-${currentJobId}` ? { ...m, content: displayContent } : m
                )
              );
            }
          });
        }
        break;
      }

      case "sources": {
        // Only process sources if we have an active job
        if (!currentJobId) return;

        const sources = (event.sources as SourceInfo[]) || [];
        sourcesRef.current = sources;
        setMessages((prev) =>
          prev.map((m) =>
            m.id === `job-${currentJobId}` ? { ...m, sources } : m
          )
        );
        break;
      }

      case "usage": {
        setTokenCount(event.total_tokens || 0);
        break;
      }

      case "done": {
        // Only process done if it's for the current job we're tracking
        // This prevents a late "done" from job 1 clearing state for job 2
        if (!currentJobId) return;

        // Cancel any pending RAF update
        if (rafIdRef.current) {
          cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
        pendingUpdateRef.current = false;

        // Reload messages from DB to get the final saved message and update cache
        listMessages(projectId, threadId)
          .then((msgs) => {
            setMessages(transformMessages(msgs));
            setCachedMessagesRef.current(threadId, msgs);
          })
          .catch((err) => {
            console.error("Failed to reload messages:", err);
          });

        // Reset refs - only if this done is for our current job
        currentJobIdRef.current = null;
        streamingRef.current = "";
        displayedRef.current = "";
        sourcesRef.current = [];
        break;
      }

      case "error": {
        // Only process error if we have an active job
        if (!currentJobId) return;

        // Cancel any pending RAF update
        if (rafIdRef.current) {
          cancelAnimationFrame(rafIdRef.current);
          rafIdRef.current = null;
        }
        pendingUpdateRef.current = false;

        const errorMessage = event.message || "Unknown error";
        console.error(`[ChatInterface] Job error: ${errorMessage}`);
        toast.error(`Response failed: ${errorMessage}`);

        // Reset refs
        currentJobIdRef.current = null;
        streamingRef.current = "";
        displayedRef.current = "";
        sourcesRef.current = [];
        break;
      }
    }
  }, [currentJobEvent, projectId, threadId, transformMessages]);

  // Cleanup RAF on unmount
  useEffect(() => {
    return () => {
      if (rafIdRef.current) {
        cancelAnimationFrame(rafIdRef.current);
      }
    };
  }, []);

  // Check for active job on mount and ensure it's running
  // State is derived from currentJobState via WebSocket - this just ensures job is started
  useEffect(() => {
    let isMounted = true;

    const checkActiveJob = async () => {
      try {
        const job = await getActiveJob(projectId, threadId);
        if (!isMounted) return;

        if (job && ["pending", "running"].includes(job.status)) {
          currentJobIdRef.current = job.id;

          // If pending, try to start it
          if (job.status === "pending") {
            try {
              await startJob(projectId, threadId, job.id);
            } catch {
              // Ignore - may already be running
            }
          }

          // Add user message and assistant placeholder if not already in messages
          setMessages((prev) => {
            const hasJobMessage = prev.some(m => m.id === `job-${job.id}`);
            const hasUserMessage = prev.some(m => m.content === job.user_message_content && m.role === "user");

            if (hasJobMessage && hasUserMessage) return prev;

            const newMessages = [...prev];

            if (!hasUserMessage) {
              newMessages.push({
                id: `user-${job.id}`,
                role: "user" as const,
                content: job.user_message_content,
              });
            }

            if (!hasJobMessage) {
              newMessages.push({
                id: `job-${job.id}`,
                role: "assistant" as const,
                content: job.partial_response || "",
                sources: job.sources_json ? JSON.parse(job.sources_json) : [],
              });
            }

            return newMessages;
          });

          // Initialize refs with any existing content
          streamingRef.current = job.partial_response || "";
          if (job.sources_json) {
            sourcesRef.current = JSON.parse(job.sources_json);
          }
        }
      } catch (error) {
        console.error("Failed to check for active job:", error);
      }
    };
    checkActiveJob();

    // Cleanup on unmount/thread change
    return () => {
      isMounted = false;
      // If we have an active job, start Celery to ensure it continues in background
      if (currentJobIdRef.current) {
        const jobIdToStart = currentJobIdRef.current;
        currentJobIdRef.current = null;
        startJob(projectId, threadId, jobIdToStart).catch(err => {
          console.error("Failed to start background job:", err);
        });
      }
    };
  }, [projectId, threadId]);

  // Note: We intentionally don't auto-scroll during streaming
  // This lets users read at their own pace without scroll hijacking
  // Scroll only happens once when user sends a message (in handleSubmit)

  // Focus input when a question is asked (desktop only)
  useEffect(() => {
    // Check window width directly since isMobile state may lag
    if (window.innerWidth < 1400) return;  // Skip on mobile/tablet to avoid keyboard popup
    const lastMessage = messages[messages.length - 1];
    if (lastMessage?.isQuestion && !isLoading && inputRef.current) {
      inputRef.current.focus();
    }
  }, [messages, isLoading]);

  const handleSubmit = useCallback(async () => {
    if (!input.trim() || isLoading) return;

    const question = input.trim();
    const tempId = `temp-${Date.now()}`;

    // Reset streaming state
    streamingRef.current = "";
    displayedRef.current = "";
    sourcesRef.current = [];
    setInput("");
    setTokenCount(0);

    // Invalidate cache since we're adding new messages
    invalidateMessageCache(threadId);

    // OPTIMISTIC UI: Show message immediately before API call
    setMessages((prev) => [
      ...prev,
      { id: tempId, role: "user" as const, content: question },
      { id: `assistant-${tempId}`, role: "assistant" as const, content: "", sources: [] }
    ]);

    // Smooth scroll to position user's message just below the sticky banner
    // Response will stream below it (like ChatGPT)
    // The streaming assistant message has min-height to create scroll room
    setTimeout(() => {
      requestAnimationFrame(() => {
        const userMessageEl = document.getElementById(`message-${tempId}`);
        const scrollContainer = scrollRef.current;
        const banner = document.getElementById("subthread-banner");

        if (userMessageEl && scrollContainer) {
          const bannerHeight = banner ? banner.offsetHeight : 0;
          const padding = bannerHeight > 0 ? 8 : 16;

          // Get message position relative to scroll content using offsetTop
          // Need to account for wrapper divs between message and scroll container
          let messageOffsetTop = 0;
          let el: HTMLElement | null = userMessageEl;
          while (el && el !== scrollContainer) {
            messageOffsetTop += el.offsetTop;
            el = el.offsetParent as HTMLElement | null;
          }

          // Target scroll: position message at (bannerHeight + padding) from visible top
          const targetScrollTop = messageOffsetTop - bannerHeight - padding;

          console.log('[SCROLL DEBUG]', {
            bannerHeight,
            padding,
            messageOffsetTop,
            targetScrollTop,
            clampedTarget: Math.max(0, targetScrollTop)
          });

          scrollContainer.scrollTo({
            top: Math.max(0, targetScrollTop),
            behavior: "smooth"
          });
        }
      });
    }, 100);

    try {
      // Create job - this saves the user message and enqueues Celery task
      const job = await createJob(projectId, threadId, question, contextOnly, true);
      const jobId = job.id;
      currentJobIdRef.current = jobId;

      // Update temp IDs with real job IDs
      setMessages((prev) => prev.map((m) =>
        m.id === tempId ? { ...m, id: `user-${jobId}` } :
        m.id === `assistant-${tempId}` ? { ...m, id: `job-${jobId}` } : m
      ));

      // Auto-generate thread title from first message if title is "New Thread"
      if (threadTitle === "New Thread" && !hasGeneratedTitleRef.current && messages.length === 0) {
        hasGeneratedTitleRef.current = true;
        generateThreadTitle(projectId, threadId, question)
          .then((updatedThread) => {
            onThreadTitleGenerated?.(updatedThread.title);
          })
          .catch((err) => {
            console.error("Failed to generate thread title:", err);
          });
      }

      // Subscribe to thread for streaming updates (ensures subscription is current)
      subscribeToThread(projectId, threadId);

    } catch (error) {
      console.error("Failed to create job:", error);
      // Remove the optimistic messages on error
      setMessages((prev) => prev.filter((m) => m.id !== tempId && m.id !== `assistant-${tempId}`));
      toast.error("Failed to send message. Please try again.");
      currentJobIdRef.current = null;
    }
  }, [input, isLoading, projectId, threadId, messages, contextOnly, threadTitle, onThreadTitleGenerated, subscribeToThread, invalidateMessageCache]);

  return (
    <div className="relative h-full flex flex-col" ref={chatContainerRef}>
      {/* Text selection menu for Dive Deeper / Save Finding */}
      <TextSelectionMenu
        onDiveDeeper={handleDiveDeeper}
        onSaveAsFinding={handleSaveAsFinding}
        containerRef={chatContainerRef}
      />

      {/* Scrollable messages area - banner is sticky INSIDE for proper scroll behavior */}
      <div
        className="flex-1 overflow-y-auto chat-scrollbar"
        ref={scrollRef}
        style={{ scrollPaddingTop: parentThreadId ? '80px' : '16px' }}
      >
        {/* Sticky context banner for child threads (subthreads) */}
        {parentThreadId && (
          <div id="subthread-banner" className="sticky top-0 z-10 border-b bg-violet-500/5 dark:bg-violet-400/5 backdrop-blur-sm bg-background/80">
            <div className="px-4 py-2.5">
              {/* Breadcrumb navigation */}
              <div className="flex items-center gap-1 text-xs mb-1.5 overflow-x-auto">
                {/* Subthread indicator icon */}
                <svg className="w-3.5 h-3.5 text-violet-600 dark:text-violet-400 flex-shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                </svg>

                {/* Ancestor breadcrumbs */}
                {onNavigateToThread && ancestorThreads.length > 0 ? (
                  <>
                    {ancestorThreads.map((ancestor, i) => (
                      <span key={ancestor.id} className="flex items-center gap-1 flex-shrink-0">
                        {i > 0 && <span className="text-muted-foreground/50">›</span>}
                        <button
                          onClick={() => onNavigateToThread({
                            id: ancestor.id,
                            project_id: projectId,
                            title: ancestor.title,
                            created_at: "",
                            updated_at: "",
                            parent_thread_id: null,
                            context_text: null,
                            child_count: 0,
                          } as Thread)}
                          className="text-muted-foreground hover:text-foreground transition-colors truncate max-w-[120px]"
                          title={ancestor.title}
                        >
                          {ancestor.title}
                        </button>
                      </span>
                    ))}
                    <span className="text-muted-foreground/50 flex-shrink-0">›</span>
                    <span className="text-violet-600 dark:text-violet-400 font-medium flex-shrink-0">Current</span>
                  </>
                ) : onNavigateToThread ? (
                  /* Fallback when no ancestor chain is available - just show back link */
                  <>
                    <button
                      onClick={() => {
                        onNavigateToThread({
                          id: parentThreadId,
                          project_id: projectId,
                          title: "",
                          created_at: "",
                          updated_at: "",
                          parent_thread_id: null,
                          context_text: null,
                          child_count: 0,
                        } as Thread);
                      }}
                      className="text-muted-foreground hover:text-foreground transition-colors"
                    >
                      Parent thread
                    </button>
                    <span className="text-muted-foreground/50">›</span>
                    <span className="text-violet-600 dark:text-violet-400 font-medium">Current</span>
                  </>
                ) : (
                  <span className="text-violet-600 dark:text-violet-400 font-medium">Deep Dive</span>
                )}
              </div>

              {/* Context text - what the user is exploring */}
              {contextText && (
                <div className="text-sm text-foreground/80 italic line-clamp-2 pl-5 border-l-2 border-violet-500/30 dark:border-violet-400/30">
                  "{contextText}"
                </div>
              )}
            </div>
          </div>
        )}

        {/* Messages container with padding */}
        <div className="p-3 md:p-4">
        <div className="space-y-3 md:space-y-4 pb-4">
          {!messagesLoaded ? (
            // Show loading state while messages are being fetched
            <div className="text-center text-muted-foreground py-12">
              <p>Loading messages...</p>
            </div>
          ) : messages.length === 0 ? (
            <div className="text-center text-muted-foreground py-12">
              <p>No messages yet.</p>
              <p className="text-sm">Upload some documents and ask a question!</p>
            </div>
          ) : (
            messages.map((message, index) => {
              // Give the last assistant message min-height to allow scrolling user message to top
              // Keep it even after streaming to avoid layout shift
              const isLastAssistant = message.role === "assistant" && index === messages.length - 1;

              return (
              <div
                key={message.id}
                id={`message-${message.id}`}
                className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
                style={isLastAssistant ? { minHeight: 'calc(100vh - 200px)' } : undefined}
              >
                <div
                  className={`max-w-[90%] md:max-w-3xl rounded-lg px-3 md:px-4 py-2 ${
                    message.role === "user"
                      ? "bg-muted text-foreground"
                      : ""
                  }`}
                >
                  <div className="text-sm">
                    {message.role === "assistant" ? (
                      <>
                        {/* 1. Status panel - shows acknowledgment first, then activity log */}
                        {isLoading && message.id === currentMessageId && (
                          <AgentStatusPanel
                            activityLog={activityLog}
                            isThinking={isThinking}
                            thinkingContent={agentThinking || ""}
                            currentAction={currentAction}
                            resourceNames={resources.filter(r => r.status === "ready").map(r => r.filename || r.source || "document")}
                            elapsedTime={elapsedTime}
                            tokenCount={tokenCount}
                            acknowledgment={acknowledgment}
                            hasContent={!!message.content}
                          />
                        )}
                        {/* 2. Response content - streams below the status */}
                        {(message.content || !isLoading) && (
                          <div className={message.isQuestion && !isLoading ? "flex items-start gap-2" : ""}>
                            {message.isQuestion && !isLoading && (
                              <span className="w-2 h-2 rounded-full bg-violet-500 inline-block flex-shrink-0 mt-1.5" />
                            )}
                            <MarkdownContent
                              content={message.content}
                              onAddUrl={async (url) => {
                                await addUrlResource(projectId, url);
                                onResourceAdded?.();
                              }}
                              isStreaming={isLoading && message.id === currentMessageId}
                            />
                          </div>
                        )}
                        {/* 3. Thinking summary - shown at bottom after response completes (only if there's actual content) */}
                        {!isLoading && message.thinking && message.thinking.trim() && (
                          <div className="mt-3">
                            <ThinkingDisplay
                              content={message.thinking}
                              isStreaming={false}
                            />
                          </div>
                        )}
                        {/* Child thread badges - clickable links to deep dives */}
                        {message.childThreads && message.childThreads.length > 0 && onNavigateToThread && (
                          <div className="flex flex-wrap gap-1.5 mt-3">
                            {message.childThreads.map(childThread => (
                              <button
                                key={childThread.id}
                                onClick={() => onNavigateToThread({
                                  id: childThread.id,
                                  project_id: projectId,
                                  title: childThread.title,
                                  created_at: "",
                                  updated_at: "",
                                  parent_thread_id: threadId,
                                  context_text: childThread.context_text,
                                  child_count: 0,
                                } as Thread)}
                                className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full
                                           bg-violet-500/10 text-violet-600 dark:text-violet-400
                                           text-xs hover:bg-violet-500/20 transition-colors"
                              >
                                <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                                </svg>
                                <span className="truncate max-w-[150px]">
                                  {childThread.title || (childThread.context_text ? childThread.context_text.slice(0, 30) + "..." : "Deep dive")}
                                </span>
                              </button>
                            ))}
                          </div>
                        )}
                        {/* Tool calls and sources at the bottom for completed messages */}
                        {!isLoading && (message.toolCalls?.length || (message.sources && message.sources.length > 0)) && (
                          <div className="mt-3 pt-2 border-t border-border/30">
                            {/* Tool calls toggle and details */}
                            {message.toolCalls && message.toolCalls.length > 0 && (
                              <div className="mb-2">
                                <button
                                  onClick={() => setShowToolCalls(showToolCalls === message.id ? null : message.id)}
                                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                                >
                                  {showToolCalls === message.id ? "Hide" : "Show"} {message.toolCalls.length} tool call{message.toolCalls.length !== 1 ? "s" : ""}
                                </button>
                                {showToolCalls === message.id && (
                                  <div className="mt-2 space-y-1.5">
                                    {message.toolCalls.map((tc, idx) => {
                                      const config = getToolConfig(tc.tool || "unknown");
                                      const isSuccess = tc.status === "complete" && (tc.found ?? 0) > 0;
                                      const isEmpty = tc.status === "complete" && tc.found === 0;
                                      const isFailed = tc.status === "failed";

                                      return (
                                        <div
                                          key={tc.id || idx}
                                          className={`text-xs rounded-md px-2.5 py-1.5 flex items-start gap-2 ${
                                            isSuccess
                                              ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400"
                                              : isEmpty
                                                ? "bg-amber-500/10 text-amber-700 dark:text-amber-400"
                                                : isFailed
                                                  ? "bg-red-500/10 text-red-700 dark:text-red-400"
                                                  : "bg-muted/50 text-muted-foreground"
                                          }`}
                                        >
                                          <span className="flex-shrink-0">{config.icon}</span>
                                          <div className="flex-1 min-w-0">
                                            <div className="font-medium">{config.displayName}</div>
                                            {tc.query && (
                                              <div className="text-[11px] opacity-80 truncate" title={tc.query}>
                                                {tc.query}
                                              </div>
                                            )}
                                          </div>
                                          <div className="flex-shrink-0 text-right">
                                            {tc.found !== undefined && tc.found !== null && (
                                              <span className="font-medium">
                                                {tc.found} result{tc.found !== 1 ? "s" : ""}
                                              </span>
                                            )}
                                            {tc.duration_ms !== undefined && tc.duration_ms !== null && (
                                              <div className="text-[10px] opacity-60">
                                                {tc.duration_ms}ms
                                              </div>
                                            )}
                                          </div>
                                        </div>
                                      );
                                    })}
                                  </div>
                                )}
                              </div>
                            )}
                            {/* Sources toggle */}
                            {message.sources && message.sources.length > 0 && (
                              <button
                                onClick={() => setShowSources(showSources === message.id ? null : message.id)}
                                className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                              >
                                {showSources === message.id ? "Hide" : "Show"} {message.sources.length} source{message.sources.length !== 1 ? "s" : ""}
                              </button>
                            )}
                            {showSources === message.id && message.sources && (
                              <div className="mt-2 space-y-2">
                                {message.sources.map((source, j) => {
                                  const resource = findResourceForSource(source);
                                  const isPdf = resource?.filename?.toLowerCase().endsWith(".pdf");
                                  const hasGithubUrl = !!source.github_url;
                                  const isClickable = isPdf || hasGithubUrl;

                                  // Format line reference for display
                                  const lineRef = source.line_start && source.line_end
                                    ? source.line_start === source.line_end
                                      ? `L${source.line_start}`
                                      : `L${source.line_start}-${source.line_end}`
                                    : source.line_start
                                      ? `L${source.line_start}`
                                      : null;

                                  return (
                                    <div
                                      key={j}
                                      className={`text-xs bg-muted/50 rounded-lg overflow-hidden border border-border/50 ${
                                        isPdf ? "cursor-pointer hover:bg-muted/70 hover:border-primary/30 transition-all" : ""
                                      }`}
                                      onClick={() => isPdf && handleViewSource(source)}
                                    >
                                      {source.snippet && (
                                        <div className="px-3 py-2.5 text-foreground/90 text-[13px] leading-relaxed border-b border-border/30">
                                          "{source.snippet}"
                                        </div>
                                      )}
                                      <div className="px-3 py-1.5 flex items-center gap-2 text-muted-foreground bg-muted/30">
                                        {hasGithubUrl ? (
                                          // GitHub source - show as external link
                                          <a
                                            href={source.github_url!}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            onClick={(e) => e.stopPropagation()}
                                            className="font-medium text-blue-500 dark:text-blue-400 hover:underline flex items-center gap-1.5 truncate"
                                          >
                                            <svg className="w-3.5 h-3.5 flex-shrink-0" viewBox="0 0 24 24" fill="currentColor">
                                              <path d="M12 0c-6.626 0-12 5.373-12 12 0 5.302 3.438 9.8 8.207 11.387.599.111.793-.261.793-.577v-2.234c-3.338.726-4.033-1.416-4.033-1.416-.546-1.387-1.333-1.756-1.333-1.756-1.089-.745.083-.729.083-.729 1.205.084 1.839 1.237 1.839 1.237 1.07 1.834 2.807 1.304 3.492.997.107-.775.418-1.305.762-1.604-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23.957-.266 1.983-.399 3.003-.404 1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222v3.293c0 .319.192.694.801.576 4.765-1.589 8.199-6.086 8.199-11.386 0-6.627-5.373-12-12-12z"/>
                                            </svg>
                                            <span className="truncate">{source.source}</span>
                                          </a>
                                        ) : (
                                          <span className={`font-medium truncate ${isPdf ? "text-primary/80" : ""}`}>
                                            {source.source.split("/").pop()}
                                          </span>
                                        )}
                                        {lineRef && (
                                          <span className="text-amber-500 dark:text-amber-400 font-mono text-[10px] whitespace-nowrap">{lineRef}</span>
                                        )}
                                        {source.page_ref && (
                                          <span className="text-blue-500 dark:text-blue-400 font-medium whitespace-nowrap">{source.page_ref}</span>
                                        )}
                                        <span className="opacity-50 text-[10px]">({(source.score * 100).toFixed(0)}% match)</span>
                                        {isPdf && (
                                          <span className="ml-auto text-primary/60 text-[10px] whitespace-nowrap">View PDF</span>
                                        )}
                                        {hasGithubUrl && !isPdf && (
                                          <span className="ml-auto text-blue-500/60 text-[10px] whitespace-nowrap flex items-center gap-0.5">
                                            <svg className="w-2.5 h-2.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10 6H6a2 2 0 00-2 2v10a2 2 0 002 2h10a2 2 0 002-2v-4M14 4h6m0 0v6m0-6L10 14" />
                                            </svg>
                                            GitHub
                                          </span>
                                        )}
                                      </div>
                                    </div>
                                  );
                                })}
                              </div>
                            )}
                          </div>
                        )}
                      </>
                    ) : (
                      <p className="whitespace-pre-wrap">{message.content}</p>
                    )}
                  </div>
                </div>
              </div>
            );})
          )}
        </div>
        </div>
      </div>

      {/* Fixed input at bottom */}
      {(() => {
        const lastMessage = messages[messages.length - 1];
        const isRespondMode = lastMessage?.isQuestion && !isLoading;
        return (
          <div className="flex-shrink-0 px-2 py-1.5 sm:p-3 md:p-4 pb-[max(0.375rem,env(safe-area-inset-bottom))] sm:pb-[max(0.75rem,env(safe-area-inset-bottom))] bg-background">
              {/* Floating input container */}
              <div className="border border-border bg-card rounded-xl shadow-sm overflow-hidden">
                {/* Single row input on mobile, two rows on desktop */}
                <div className="flex items-end gap-1.5 p-1.5 sm:p-2 sm:pb-0">
                  <Textarea
                    ref={inputRef}
                    placeholder={isRespondMode ? "Type your response..." : "Ask a question..."}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === "Enter" && !e.shiftKey) {
                        e.preventDefault();
                        handleSubmit();
                      }
                    }}
                    className="min-h-[36px] sm:min-h-[40px] max-h-[200px] resize-none flex-1 text-[15px] sm:text-sm border-0 bg-transparent focus-visible:ring-0 focus-visible:ring-offset-0 shadow-none py-1.5 px-2"
                    rows={1}
                  />
                  {/* Mobile: Icon buttons inline */}
                  <div className="flex items-center gap-1 sm:hidden pb-0.5">
                    <Popover>
                      <PopoverTrigger asChild>
                        <button
                          className={`h-9 w-9 flex items-center justify-center rounded-lg transition-colors relative shrink-0 ${
                            contextOnly
                              ? "bg-amber-500/20 text-amber-600 dark:text-amber-400"
                              : "bg-muted/50 text-muted-foreground active:bg-muted"
                          }`}
                          title="Search settings"
                        >
                          <svg
                            className="w-[18px] h-[18px]"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={1.75}
                              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                          </svg>
                          {contextOnly && (
                            <span className="absolute top-1 right-1 w-2 h-2 rounded-full bg-amber-500" />
                          )}
                        </button>
                      </PopoverTrigger>
                      <PopoverContent className="w-44 p-1.5" align="end" sideOffset={8}>
                        <button
                          onClick={() => setContextOnly(!contextOnly)}
                          className={`w-full flex items-center gap-2.5 px-3 py-2.5 rounded-lg text-sm font-medium transition-colors ${
                            contextOnly
                              ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                              : "hover:bg-muted"
                          }`}
                        >
                          <svg
                            className="w-4 h-4 shrink-0"
                            fill="none"
                            stroke="currentColor"
                            viewBox="0 0 24 24"
                          >
                            <path
                              strokeLinecap="round"
                              strokeLinejoin="round"
                              strokeWidth={2}
                              d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                          </svg>
                          Docs only
                          {contextOnly && (
                            <svg className="w-4 h-4 ml-auto shrink-0 text-amber-600 dark:text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2.5} d="M5 13l4 4L19 7" />
                            </svg>
                          )}
                        </button>
                      </PopoverContent>
                    </Popover>
                    <button
                      onClick={handleSubmit}
                      disabled={isLoading || !input.trim()}
                      className={`h-9 w-9 flex items-center justify-center rounded-lg transition-colors shrink-0 disabled:opacity-40 ${
                        isRespondMode
                          ? "bg-violet-600 text-white active:bg-violet-700"
                          : "bg-primary text-primary-foreground active:bg-primary/90"
                      }`}
                      title={isRespondMode ? "Reply" : "Send"}
                    >
                      {isRespondMode ? (
                        <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                        </svg>
                      ) : (
                        <svg className="w-[18px] h-[18px]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>
                {/* Desktop: Full action buttons row */}
                <div className="hidden sm:flex items-center justify-between px-2 pb-2">
                  <button
                    onClick={() => setContextOnly(!contextOnly)}
                    className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs font-medium transition-colors ${
                      contextOnly
                        ? "bg-amber-500/15 text-amber-600 dark:text-amber-400"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                    title={contextOnly ? "Only answering from documents" : "Click to restrict answers to documents only"}
                  >
                    <svg
                      className="w-3.5 h-3.5"
                      fill="none"
                      stroke="currentColor"
                      viewBox="0 0 24 24"
                    >
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                      />
                    </svg>
                    Docs only
                    {contextOnly && (
                      <span className="w-1.5 h-1.5 rounded-full bg-amber-500 animate-pulse" />
                    )}
                  </button>
                  <Button
                    onClick={handleSubmit}
                    disabled={isLoading || !input.trim()}
                    size="sm"
                    className={`h-8 w-8 p-0 shrink-0 ${isRespondMode ? "bg-violet-600 hover:bg-violet-700 text-white" : ""}`}
                    title={isRespondMode ? "Reply" : "Send"}
                  >
                    {isRespondMode ? (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 10h10a8 8 0 018 8v2M3 10l6 6m-6-6l6-6" />
                      </svg>
                    ) : (
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 10l7-7m0 0l7 7m-7-7v18" />
                      </svg>
                    )}
                  </Button>
                </div>
              </div>
          </div>
        );
      })()}

      {/* PDF viewer dialog for viewing sources */}
      <Dialog open={!!viewingSource} onOpenChange={() => setViewingSource(null)}>
        <DialogContent className="w-[95vw] !max-w-[95vw] h-[95vh] flex flex-col">
          <DialogHeader>
            <DialogTitle>
              {viewingSource?.filename}
              {viewingSource?.pageNumber && viewingSource.pageNumber > 1 && (
                <span className="text-muted-foreground ml-2 text-sm font-normal">
                  (Page {viewingSource.pageNumber})
                </span>
              )}
            </DialogTitle>
          </DialogHeader>
          <div className="flex-1 overflow-hidden">
            {viewingSource && (
              <PdfViewer
                url={getResourceFileUrl(projectId, viewingSource.resourceId)}
                initialPage={viewingSource.pageNumber}
              />
            )}
          </div>
        </DialogContent>
      </Dialog>

      {/* Rules dialog */}
      <Dialog open={isRulesDialogOpen} onOpenChange={setIsRulesDialogOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Project Rules</DialogTitle>
            <DialogDescription>
              Add rules to guide how the AI responds in this project.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 pt-2">
            {/* Existing rules list */}
            {rules.length > 0 && (
              <div className="space-y-2">
                {rules.map((rule, index) => (
                  <div
                    key={index}
                    className="flex items-start gap-2 p-2 bg-muted/50 rounded-md group"
                  >
                    <span className="flex-1 text-sm">{rule}</span>
                    <button
                      onClick={() => {
                        const newRules = rules.filter((_, i) => i !== index);
                        onRulesChange?.(newRules);
                      }}
                      className="text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity p-1"
                    >
                      <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                        <path d="M18 6 6 18" />
                        <path d="m6 6 12 12" />
                      </svg>
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* Add new rule */}
            <div className="flex gap-2">
              <Input
                placeholder="Add a rule..."
                value={newRuleInput}
                onChange={(e) => setNewRuleInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && newRuleInput.trim()) {
                    onRulesChange?.([...rules, newRuleInput.trim()]);
                    setNewRuleInput("");
                  }
                }}
              />
              <Button
                onClick={() => {
                  if (newRuleInput.trim()) {
                    onRulesChange?.([...rules, newRuleInput.trim()]);
                    setNewRuleInput("");
                  }
                }}
                disabled={!newRuleInput.trim()}
                size="sm"
              >
                Add
              </Button>
            </div>

            {rules.length === 0 && (
              <p className="text-xs text-muted-foreground text-center py-2">
                No rules yet. Add rules to customize AI behavior.
              </p>
            )}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
