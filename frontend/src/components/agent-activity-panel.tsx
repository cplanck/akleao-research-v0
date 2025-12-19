"use client";

import { useState, useEffect } from "react";
import { ChevronUp, ChevronDown } from "lucide-react";
import { getToolConfig } from "@/lib/tool-registry";

interface ToolCallRecord {
  id?: string;
  tool?: string;
  name?: string;
  query?: string | null;
  found?: number | null;
  timestamp?: number | null;
  status?: "running" | "complete" | "empty" | "failed";
  duration_ms?: number | null;
}

interface ActivityLogItem {
  id: string;
  type: "tool_call" | "tool_result" | "phase_change" | "thinking_start";
  timestamp: number;
  name?: string;
  tool?: string;
  query?: string;
  found?: number;
  status?: string;
  duration_ms?: number;
}

interface AgentActivityPanelProps {
  isActive: boolean;
  activityLog: ActivityLogItem[];
  currentPhase: string;
  acknowledgment?: string;
  elapsedTime?: number;
  tokenCount?: number;
}

// Format elapsed time
function formatTime(seconds: number): string {
  if (seconds < 60) {
    return `${seconds}s`;
  }
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins}m ${secs}s`;
}

// Get status indicator
function getStatusIndicator(status?: string): { symbol: string; className: string } {
  switch (status) {
    case "complete":
      return { symbol: "✓", className: "text-emerald-400" };
    case "failed":
      return { symbol: "✗", className: "text-red-400" };
    case "empty":
      return { symbol: "○", className: "text-amber-400" };
    case "running":
    default:
      return { symbol: "◌", className: "text-blue-400 animate-pulse" };
  }
}

// Phase display text
function getPhaseDisplay(phase: string): string {
  switch (phase) {
    case "initializing":
      return "Initializing...";
    case "planning":
      return "Planning";
    case "searching":
      return "Searching";
    case "processing":
      return "Processing";
    case "thinking":
      return "Thinking";
    case "synthesizing":
      return "Synthesizing";
    case "cooking":
      return "Working...";
    case "finishing":
    case "responding":
      return "Responding";
    case "done":
      return "Done";
    default:
      return "Working";
  }
}

export function AgentActivityPanel({
  isActive,
  activityLog,
  currentPhase,
  acknowledgment,
  elapsedTime = 0,
}: AgentActivityPanelProps) {
  const [isExpanded, setIsExpanded] = useState(true);
  const [isVisible, setIsVisible] = useState(false);
  const [shouldRender, setShouldRender] = useState(false);

  // Handle visibility and animation states
  useEffect(() => {
    if (isActive) {
      // Show immediately when active
      setShouldRender(true);
      // Small delay to ensure render before animation
      requestAnimationFrame(() => {
        setIsVisible(true);
        setIsExpanded(true);
      });
    } else if (isVisible) {
      // Just finished - collapse first, then hide
      const collapseTimer = setTimeout(() => {
        setIsExpanded(false);
      }, 1500); // Wait 1.5s showing "Done" before collapsing

      const hideTimer = setTimeout(() => {
        setIsVisible(false);
      }, 1800); // Start fade out

      const removeTimer = setTimeout(() => {
        setShouldRender(false);
      }, 2200); // Remove from DOM after fade completes

      return () => {
        clearTimeout(collapseTimer);
        clearTimeout(hideTimer);
        clearTimeout(removeTimer);
      };
    }
  }, [isActive, isVisible]);

  // Build tool call list with results merged
  const toolCalls = activityLog.reduce<ToolCallRecord[]>((acc, item) => {
    if (item.type === "tool_call") {
      acc.push({
        id: item.id,
        tool: item.tool || item.name,
        name: item.name || item.tool,
        query: item.query,
        timestamp: item.timestamp,
        status: "running",
      });
    } else if (item.type === "tool_result") {
      const lastPending = [...acc].reverse().find(tc => tc.status === "running");
      if (lastPending) {
        lastPending.status = item.found === 0 ? "empty" : item.status === "failed" ? "failed" : "complete";
        lastPending.found = item.found;
        lastPending.duration_ms = item.duration_ms;
      }
    }
    return acc;
  }, []);

  const phaseText = getPhaseDisplay(currentPhase);

  if (!shouldRender) {
    return null;
  }

  return (
    <div
      className={`transition-all duration-300 ease-out origin-bottom ${
        isVisible
          ? "opacity-100 translate-y-0"
          : "opacity-0 translate-y-4 pointer-events-none"
      }`}
    >
      {/* Drawer container - tucked behind input, extra padding when expanded for overlap */}
      <div className={`bg-muted/50 dark:bg-muted/30 border border-border rounded-xl overflow-hidden backdrop-blur-sm transition-all duration-300 ${
        isExpanded ? "pb-4" : ""
      }`}>
        {/* Header - clickable to expand/collapse */}
        <button
          onClick={() => setIsExpanded(!isExpanded)}
          className="w-full flex items-center gap-3 px-3 py-1.5 hover:bg-muted/50 transition-colors font-mono text-xs"
        >
          {/* Status indicator */}
          {isActive ? (
            <span className="text-blue-400 animate-pulse">◌</span>
          ) : (
            <span className="text-emerald-400">✓</span>
          )}

          {/* Phase text */}
          <span className="flex-1 text-left text-foreground/90">
            {isActive ? phaseText : "Done"}
          </span>

          {/* Timer */}
          {elapsedTime > 0 && (
            <span className="text-muted-foreground tabular-nums">
              {formatTime(elapsedTime)}
            </span>
          )}

          {/* Expand/collapse chevron */}
          {isExpanded ? (
            <ChevronDown className="w-3.5 h-3.5 text-muted-foreground" />
          ) : (
            <ChevronUp className="w-3.5 h-3.5 text-muted-foreground" />
          )}
        </button>

        {/* Expandable content area - only render if there's content to show */}
        {(toolCalls.length > 0 || acknowledgment || isActive) && (
          <div
            className={`overflow-hidden transition-all duration-300 ease-out ${
              isExpanded ? "max-h-52 opacity-100" : "max-h-0 opacity-0"
            }`}
          >
            <div className="px-3 pb-3 pt-1 space-y-1.5 font-mono text-xs">
              {/* Acknowledgment */}
              {acknowledgment && (
                <div className="text-muted-foreground/80 pl-5 leading-relaxed">
                  {acknowledgment}
                </div>
              )}

              {/* Tool calls list */}
              {toolCalls.map((tool, idx) => {
                const statusInfo = getStatusIndicator(tool.status);
                const toolName = getToolConfig(tool.tool || tool.name || "").displayName;

                return (
                  <div key={tool.id || idx} className="flex items-start gap-2 leading-relaxed">
                    <span className={`w-4 text-center flex-shrink-0 ${statusInfo.className}`}>
                      {statusInfo.symbol}
                    </span>
                    <div className="flex-1 min-w-0 text-foreground/80">
                      <span className="text-foreground/90">{toolName}</span>
                      {tool.query && (
                        <span className="text-muted-foreground"> "{tool.query}"</span>
                      )}
                      {tool.found !== null && tool.found !== undefined && (
                        <span className={tool.found === 0 ? "text-amber-400" : "text-muted-foreground"}>
                          {" → "}{tool.found} result{tool.found !== 1 ? "s" : ""}
                        </span>
                      )}
                      {tool.duration_ms && (
                        <span className="text-muted-foreground/50"> {tool.duration_ms}ms</span>
                      )}
                    </div>
                  </div>
                );
              })}

              {/* Empty state - only when active */}
              {toolCalls.length === 0 && !acknowledgment && isActive && (
                <div className="text-muted-foreground/60 pl-5">
                  Waiting...
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
