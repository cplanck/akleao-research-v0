import { Tool, ToolContext, ToolResult } from "./types";

/**
 * Get Resource Info Tool
 *
 * Gets detailed information about a specific resource including
 * its type, status, and summary.
 */
export const getResourceInfo: Tool = {
  name: "get_resource_info",

  definition: {
    name: "get_resource_info",
    description:
      "Get detailed information about a specific resource including its type, status, and summary. For PDFs and documents, use search_documents to find content.",
    input_schema: {
      type: "object" as const,
      properties: {
        resource_name: {
          type: "string",
          description: "The name of the resource to get info about",
        },
      },
      required: ["resource_name"],
    },
  },

  async execute(
    input: Record<string, unknown>,
    context: ToolContext
  ): Promise<ToolResult> {
    const resourceName = input.resource_name as string;

    // Fetch all resources to find the matching one
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
    const resource = resources.find(
      (r: { filename: string }) =>
        r.filename.toLowerCase() === resourceName.toLowerCase()
    );

    if (!resource) {
      return {
        success: false,
        content: `Resource "${resourceName}" not found. Use list_resources to see available files.`,
        metadata: { found: 0, query: resourceName },
      };
    }

    // Build resource info
    let info = `**${resource.filename}**\n`;
    info += `- Type: ${resource.type}\n`;
    info += `- Status: ${resource.status}\n`;

    if (resource.summary) {
      info += `\n**Summary:**\n${resource.summary}\n`;
    }

    if (resource.type === "document") {
      info += `\n*To search within this document, use search_documents with relevant keywords.*`;
    }

    return {
      success: true,
      content: info,
      metadata: { found: 1, query: resourceName },
    };
  },
};
