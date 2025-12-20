"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { useAuth } from "@/contexts/auth-context";
import { MarkdownContent } from "@/components/markdown-content";

// Hardcoded project ID - must match the one in the API route
const PROJECT_ID = "01100eb0-9581-42fe-8446-aea1298753b4";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

interface ToolCall {
  id: string;
  tool: string;
  input?: Record<string, unknown>;
  status: "pending" | "executing" | "complete" | "error";
  metadata?: Record<string, unknown>;
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  toolCalls?: ToolCall[]; // Store tool calls with the message
}

interface Resource {
  id: string;
  filename: string;
  type: string;
  status: string;
  summary?: string;
}


export default function AgentV5Page() {
  const { isAuthenticated, loading } = useAuth();
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [toolCalls, setToolCalls] = useState<ToolCall[]>([]);
  const [streamingContent, setStreamingContent] = useState("");
  const [resources, setResources] = useState<Resource[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Use ref to track tool calls for the "done" handler to avoid nested state updates
  const toolCallsRef = useRef<ToolCall[]>([]);

  // Fetch resources on mount
  useEffect(() => {
    async function fetchResources() {
      try {
        const res = await fetch(`${API_BASE}/projects/${PROJECT_ID}/resources`, {
          credentials: "include",
        });
        if (res.ok) {
          const data = await res.json();
          setResources(data);
        }
      } catch (err) {
        console.error("Failed to fetch resources:", err);
      }
    }
    if (isAuthenticated) {
      fetchResources();
    }
  }, [isAuthenticated]);

  // Auto-scroll to bottom when new content arrives
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages, streamingContent, toolCalls]);

  const handleSubmit = async () => {
    if (!input.trim() || isLoading || !isAuthenticated) return;

    const userMessage: Message = {
      id: `user-${Date.now()}`,
      role: "user",
      content: input.trim(),
    };

    setMessages((prev) => [...prev, userMessage]);
    setInput("");
    setIsLoading(true);
    setStreamingContent("");
    setToolCalls([]);
    toolCallsRef.current = [];

    try {
      const response = await fetch("/api/agent-v5", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include", // Forward cookies
        body: JSON.stringify({
          messages: [...messages, userMessage].map((m) => ({
            role: m.role,
            content: m.content,
          })),
        }),
      });

      if (!response.ok) {
        throw new Error(`HTTP error: ${response.status}`);
      }

      const reader = response.body?.getReader();
      if (!reader) throw new Error("No reader");

      const decoder = new TextDecoder();
      let buffer = "";
      let fullContent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("data: ")) {
            try {
              const data = JSON.parse(line.slice(6));

              switch (data.type) {
                case "text":
                  fullContent += data.content;
                  setStreamingContent(fullContent);
                  break;

                case "tool_call_start": {
                  const newTc: ToolCall = {
                    id: data.id,
                    tool: data.tool,
                    status: "pending",
                  };
                  toolCallsRef.current = [...toolCallsRef.current, newTc];
                  setToolCalls(toolCallsRef.current);
                  break;
                }

                case "tool_call":
                  toolCallsRef.current = toolCallsRef.current.map((tc) =>
                    tc.id === data.id
                      ? { ...tc, input: data.input, status: "executing" as const }
                      : tc
                  );
                  setToolCalls(toolCallsRef.current);
                  break;

                case "tool_executing":
                  toolCallsRef.current = toolCallsRef.current.map((tc) =>
                    tc.id === data.id ? { ...tc, status: "executing" as const } : tc
                  );
                  setToolCalls(toolCallsRef.current);
                  break;

                case "tool_result": {
                  const resultStatus: ToolCall["status"] = data.success ? "complete" : "error";
                  toolCallsRef.current = toolCallsRef.current.map((tc) =>
                    tc.id === data.id
                      ? { ...tc, status: resultStatus, metadata: data.metadata }
                      : tc
                  );
                  setToolCalls(toolCallsRef.current);
                  break;
                }

                case "done": {
                  // Clear streaming content FIRST to prevent duplication
                  setStreamingContent("");
                  // Add assistant message to history with its tool calls (use ref to avoid nested updates)
                  const finalToolCalls = toolCallsRef.current;
                  if (fullContent || finalToolCalls.length > 0) {
                    setMessages((prev) => [
                      ...prev,
                      {
                        id: `assistant-${Date.now()}`,
                        role: "assistant",
                        content: fullContent,
                        toolCalls: finalToolCalls.length > 0 ? [...finalToolCalls] : undefined,
                      },
                    ]);
                  }
                  // Clear tool calls
                  toolCallsRef.current = [];
                  setToolCalls([]);
                  break;
                }

                case "error":
                  console.error("Agent error:", data.error);
                  setMessages((prev) => [
                    ...prev,
                    {
                      id: `error-${Date.now()}`,
                      role: "assistant",
                      content: `Error: ${data.error}`,
                    },
                  ]);
                  break;
              }
            } catch (e) {
              console.error("Failed to parse SSE data:", e);
            }
          }
        }
      }
    } catch (error) {
      console.error("Request failed:", error);
      setMessages((prev) => [
        ...prev,
        {
          id: `error-${Date.now()}`,
          role: "assistant",
          content: `Request failed: ${error instanceof Error ? error.message : "Unknown error"}`,
        },
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  const getToolIcon = (status: ToolCall["status"]) => {
    switch (status) {
      case "pending":
        return "○";
      case "executing":
        return "◌";
      case "complete":
        return "✓";
      case "error":
        return "✗";
    }
  };

  const getToolStatusClass = (status: ToolCall["status"]) => {
    switch (status) {
      case "pending":
        return "text-gray-400";
      case "executing":
        return "text-blue-400 animate-pulse";
      case "complete":
        return "text-emerald-400";
      case "error":
        return "text-red-400";
    }
  };

  return (
    <div className="flex h-screen bg-background">
      {/* Main chat area */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Header */}
        <div className="border-b px-4 py-3">
          <h1 className="text-lg font-semibold">Agent V5 - Experiment</h1>
          <p className="text-sm text-muted-foreground">
            Simple loop with Claude API + tools
          </p>
        </div>

        {/* Chat area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto p-4 space-y-4">
        {messages.map((message) => (
          <div
            key={message.id}
            className={`flex ${message.role === "user" ? "justify-end" : "justify-start"}`}
          >
            <div
              className={`max-w-[80%] rounded-lg px-4 py-2 ${
                message.role === "user"
                  ? "bg-primary text-primary-foreground"
                  : "bg-none"
              }`}
            >
              {/* Show tool calls for this message (if any) */}
              {message.toolCalls && message.toolCalls.length > 0 && (
                <div className="mb-3 pb-3 border-b border-border/50 space-y-1.5 font-mono text-xs">
                  {message.toolCalls.map((tc) => (
                    <div key={tc.id} className="flex items-start gap-2">
                      <span className={getToolStatusClass(tc.status)}>
                        {getToolIcon(tc.status)}
                      </span>
                      <div className="flex-1">
                        <span className="font-medium">{tc.tool}</span>
                        {tc.input && (
                          <span className="text-muted-foreground ml-2">
                            {JSON.stringify(tc.input)}
                          </span>
                        )}
                        {tc.metadata?.found !== undefined && (
                          <span className="text-muted-foreground ml-2">
                            → {String(tc.metadata.found)} results
                          </span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {message.role === "assistant" ? (
                <MarkdownContent content={message.content} />
              ) : (
                <p className="whitespace-pre-wrap text-sm">{message.content}</p>
              )}
            </div>
          </div>
        ))}

        {/* Active tool calls (during streaming) */}
        {toolCalls.length > 0 && (
          <div className="bg-muted/50 rounded-lg p-3 space-y-2 font-mono text-xs">
            <div className="text-muted-foreground font-semibold mb-2">
              Tool Calls
            </div>
            {toolCalls.map((tc) => (
              <div key={tc.id} className="flex items-start gap-2">
                <span className={getToolStatusClass(tc.status)}>
                  {getToolIcon(tc.status)}
                </span>
                <div className="flex-1">
                  <span className="font-medium">{tc.tool}</span>
                  {tc.input && (
                    <span className="text-muted-foreground ml-2">
                      {JSON.stringify(tc.input)}
                    </span>
                  )}
                  {tc.metadata?.found !== undefined && (
                    <span className="text-muted-foreground ml-2">
                      → {String(tc.metadata.found)} results
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}

        {/* Streaming content - only show while loading */}
        {isLoading && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-lg px-4 py-2 bg-muted">
              <MarkdownContent content={streamingContent} isStreaming />
            </div>
          </div>
        )}

        {/* Loading indicator when waiting for first response */}
        {isLoading && !streamingContent && toolCalls.length === 0 && (
          <div className="flex justify-start">
            <div className="rounded-lg px-4 py-2 bg-muted">
              <span className="text-muted-foreground">...</span>
            </div>
          </div>
        )}
      </div>

        {/* Input area */}
        <div className="border-t p-4">
          <div className="flex gap-2">
            <Textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  handleSubmit();
                }
              }}
              placeholder="Ask a question..."
              className="min-h-[44px] max-h-[200px] resize-none"
              rows={1}
              disabled={isLoading}
            />
            <Button
              onClick={handleSubmit}
              disabled={isLoading || !input.trim() || !isAuthenticated || loading}
              className="shrink-0"
            >
              {isLoading ? "..." : "Send"}
            </Button>
          </div>
          {!loading && !isAuthenticated && (
            <p className="text-sm text-red-500 mt-2">
              Not authenticated. Please log in first.
            </p>
          )}
        </div>
      </div>

      {/* Resources sidebar */}
      <div className="w-72 border-l bg-muted/30 flex flex-col">
        <div className="p-3 border-b">
          <h2 className="font-semibold text-sm">Resources</h2>
          <p className="text-xs text-muted-foreground">{resources.length} files</p>
        </div>
        <div className="flex-1 overflow-y-auto p-2 space-y-1">
          {resources.length === 0 ? (
            <p className="text-xs text-muted-foreground p-2">No resources found</p>
          ) : (
            resources.map((resource) => (
              <div
                key={resource.id}
                className="p-2 rounded text-xs bg-background border hover:bg-muted/50 transition-colors"
              >
                <div className="font-medium truncate" title={resource.filename}>
                  {resource.filename}
                </div>
                <div className="flex items-center gap-2 mt-1 text-muted-foreground">
                  <span className="capitalize">{resource.type}</span>
                  <span>•</span>
                  <span className={
                    resource.status === "indexed" || resource.status === "ready"
                      ? "text-emerald-500"
                      : resource.status === "failed"
                      ? "text-red-500"
                      : "text-amber-500"
                  }>
                    {resource.status}
                  </span>
                </div>
                {resource.summary && (
                  <p className="mt-1 text-muted-foreground line-clamp-2" title={resource.summary}>
                    {resource.summary}
                  </p>
                )}
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}
