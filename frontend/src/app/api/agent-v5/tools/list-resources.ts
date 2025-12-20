import { Tool, ToolContext, ToolResult } from "./types";

/**
 * List Resources Tool
 *
 * Lists all resources (documents, files, images) in the user's
 * workspace with optional filtering by type.
 */
export const listResources: Tool = {
  name: "list_resources",

  definition: {
    name: "list_resources",
    description:
      "List all resources (documents, files, images) in the user's workspace. Use this to see what's available before searching.",
    input_schema: {
      type: "object" as const,
      properties: {
        type_filter: {
          type: "string",
          enum: ["document", "data_file", "image", "website", "git_repository"],
          description: "Optional filter by resource type",
        },
      },
      required: [],
    },
  },

  async execute(
    input: Record<string, unknown>,
    context: ToolContext
  ): Promise<ToolResult> {
    const typeFilter = input.type_filter as string | undefined;

    const res = await fetch(
      `${context.apiBase}/projects/${context.projectId}/resources`,
      {
        headers: {
          Cookie: context.cookieHeader,
        },
      }
    );

    if (!res.ok) {
      throw new Error(`List resources failed: ${res.status}`);
    }

    const resources = await res.json();

    if (resources.length === 0) {
      return {
        success: true,
        content: "No resources found in this workspace.",
        metadata: { found: 0 },
      };
    }

    const filtered = typeFilter
      ? resources.filter((r: { type: string }) => r.type === typeFilter)
      : resources;

    const formatted = filtered
      .map(
        (r: { filename: string; type: string; status: string }) =>
          `- ${r.filename} (${r.type}, ${r.status})`
      )
      .join("\n");

    return {
      success: true,
      content: `Found ${filtered.length} resources:\n${formatted}`,
      metadata: { found: filtered.length },
    };
  },
};
