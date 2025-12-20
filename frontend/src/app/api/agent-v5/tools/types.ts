import Anthropic from "@anthropic-ai/sdk";

/**
 * Context passed to tool execution - contains auth and config
 */
export interface ToolContext {
  cookieHeader: string;
  projectId: string;
  apiBase: string;
}

/**
 * Result returned from tool execution
 */
export interface ToolResult {
  success: boolean;
  content: string;
  metadata?: Record<string, unknown>;
}

/**
 * A tool definition with schema and executor
 */
export interface Tool {
  /** Tool name - must match the name in the schema */
  name: string;

  /** Tool schema for Claude API */
  definition: Anthropic.Tool;

  /** Execute the tool with given input and context */
  execute: (
    input: Record<string, unknown>,
    context: ToolContext
  ) => Promise<ToolResult>;
}
