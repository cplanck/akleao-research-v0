import { Tool, ToolContext, ToolResult } from "./types";

/**
 * Search Documents Tool
 *
 * Performs semantic search over the user's uploaded documents
 * using the backend search API.
 */
export const searchDocuments: Tool = {
  name: "search_documents",

  definition: {
    name: "search_documents",
    description:
      "Search the user's uploaded documents and workspace using semantic search. Use this to find relevant information from their files.",
    input_schema: {
      type: "object" as const,
      properties: {
        query: {
          type: "string",
          description:
            "The search query - use specific keywords related to what you're looking for",
        },
      },
      required: ["query"],
    },
  },

  async execute(
    input: Record<string, unknown>,
    context: ToolContext
  ): Promise<ToolResult> {
    const query = input.query as string;

    const res = await fetch(
      `${context.apiBase}/projects/${context.projectId}/search`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          Cookie: context.cookieHeader,
        },
        body: JSON.stringify({ query, top_k: 10 }),
      }
    );

    if (!res.ok) {
      throw new Error(`Search failed: ${res.status}`);
    }

    const data = await res.json();
    const results = data.results || [];

    if (results.length === 0) {
      return {
        success: true,
        content: `No results found for "${query}"`,
        metadata: { query, found: 0 },
      };
    }

    const formatted = results
      .map(
        (r: { source: string; snippet: string; score: number }, i: number) =>
          `[${i + 1}] ${r.source}\n${r.snippet}\n(Score: ${(r.score * 100).toFixed(0)}%)`
      )
      .join("\n\n");

    return {
      success: true,
      content: `Found ${results.length} results for "${query}":\n\n${formatted}`,
      metadata: { query, found: results.length },
    };
  },
};
