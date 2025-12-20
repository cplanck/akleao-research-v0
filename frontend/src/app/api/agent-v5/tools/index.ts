import Anthropic from "@anthropic-ai/sdk";
import { Tool, ToolContext, ToolResult } from "./types";

// Import all tools
import { searchDocuments } from "./search-documents";
import { searchWeb } from "./search-web";
import { listResources } from "./list-resources";
import { getResourceInfo } from "./get-resource-info";

// Re-export types
export type { ToolContext, ToolResult } from "./types";

/**
 * Registry of all available tools
 */
const toolRegistry: Tool[] = [
  searchDocuments,
  searchWeb,
  listResources,
  getResourceInfo,
];

/**
 * Get all tool definitions for the Claude API
 */
export function getToolDefinitions(): Anthropic.Tool[] {
  return toolRegistry.map((t) => t.definition);
}

/**
 * Execute a tool by name
 */
export async function executeTool(
  name: string,
  input: Record<string, unknown>,
  context: ToolContext
): Promise<ToolResult> {
  const tool = toolRegistry.find((t) => t.name === name);

  if (!tool) {
    return {
      success: false,
      content: `Unknown tool: ${name}`,
    };
  }

  try {
    return await tool.execute(input, context);
  } catch (error) {
    return {
      success: false,
      content: `Tool error: ${error instanceof Error ? error.message : "Unknown error"}`,
    };
  }
}
