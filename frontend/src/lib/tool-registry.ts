/**
 * Tool Registry - Centralized configuration for tool display metadata.
 *
 * This module mirrors the backend rag/tool_registry.py to ensure
 * consistent display across the application.
 */

export interface ToolDisplayConfig {
  id: string;
  displayName: string;
  icon: string;
  inProgressTemplate: string;
  completeTemplate: string;
  failedTemplate: string;
}

/**
 * Registry of all tools with their display configurations.
 * Keep in sync with backend rag/tool_registry.py
 */
export const TOOL_REGISTRY: Record<string, ToolDisplayConfig> = {
  search_documents: {
    id: "search_documents",
    displayName: "Document Search",
    icon: "📄",
    inProgressTemplate: "Searching documents for '{query}'",
    completeTemplate: "Found {count} results in documents",
    failedTemplate: "No relevant documents found",
  },
  search_web: {
    id: "search_web",
    displayName: "Web Search",
    icon: "🌐",
    inProgressTemplate: "Searching the web for '{query}'",
    completeTemplate: "Found {count} web results",
    failedTemplate: "No web results found",
  },
  analyze_data: {
    id: "analyze_data",
    displayName: "Data Analysis",
    icon: "📊",
    inProgressTemplate: "Analyzing '{resource}'",
    completeTemplate: "Completed analysis of '{resource}'",
    failedTemplate: "Failed to analyze data",
  },
  view_image: {
    id: "view_image",
    displayName: "Image Analysis",
    icon: "🖼️",
    inProgressTemplate: "Analyzing image '{resource}'",
    completeTemplate: "Analyzed '{resource}'",
    failedTemplate: "Failed to analyze image",
  },
  save_finding: {
    id: "save_finding",
    displayName: "Save Finding",
    icon: "💾",
    inProgressTemplate: "Saving finding...",
    completeTemplate: "Finding saved successfully",
    failedTemplate: "Failed to save finding",
  },
};

/**
 * Get display config for a tool, with fallback for unknown tools.
 */
export function getToolConfig(toolId: string): ToolDisplayConfig {
  if (toolId in TOOL_REGISTRY) {
    return TOOL_REGISTRY[toolId];
  }

  // Fallback for unknown tools
  const displayName = toolId
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());

  return {
    id: toolId,
    displayName,
    icon: "⚙️",
    inProgressTemplate: `Running ${displayName.toLowerCase()}...`,
    completeTemplate: `${displayName} completed`,
    failedTemplate: `${displayName} failed`,
  };
}

/**
 * Format a tool status message using the registry.
 *
 * @param toolId - Tool identifier (e.g., "search_documents")
 * @param stage - One of "in_progress", "complete", or "failed"
 * @param context - Object with template variables like query, resource, count
 * @returns Formatted status string for display
 *
 * @example
 * formatToolStatus("search_web", "in_progress", { query: "climate change" })
 * // Returns: "Searching the web for 'climate change'"
 *
 * formatToolStatus("search_web", "complete", { count: 5 })
 * // Returns: "Found 5 web results"
 */
export function formatToolStatus(
  toolId: string,
  stage: "in_progress" | "complete" | "failed",
  context: { query?: string; resource?: string; count?: number } = {}
): string {
  const config = getToolConfig(toolId);

  const templates = {
    in_progress: config.inProgressTemplate,
    complete: config.completeTemplate,
    failed: config.failedTemplate,
  };

  let template = templates[stage];

  // Replace placeholders with context values
  if (context.query !== undefined) {
    template = template.replace("{query}", context.query);
  }
  if (context.resource !== undefined) {
    template = template.replace("{resource}", context.resource);
  }
  if (context.count !== undefined) {
    template = template.replace("{count}", String(context.count));
  }

  // Remove any remaining unformatted placeholders
  template = template.replace(/\{[^}]+\}/g, "").trim();

  return template;
}

/**
 * Tool call record structure for persistence and display.
 * This matches the JSON schema stored in the database.
 */
export interface ToolCallRecord {
  id: string;
  tool: string;
  query?: string;
  resource?: string;
  timestamp: number;
  status: "running" | "complete" | "empty" | "failed";
  found?: number;
  duration_ms?: number;
}
