import { Tool, ToolContext, ToolResult } from "./types";

/**
 * Search Web Tool
 *
 * Performs web search using the Tavily API to find
 * current information from the internet.
 */
export const searchWeb: Tool = {
  name: "search_web",

  definition: {
    name: "search_web",
    description:
      "Search the internet for current information. Use this when you need up-to-date information or information not in the user's documents.",
    input_schema: {
      type: "object" as const,
      properties: {
        query: {
          type: "string",
          description: "The web search query",
        },
      },
      required: ["query"],
    },
  },

  async execute(
    input: Record<string, unknown>,
    _context: ToolContext
  ): Promise<ToolResult> {
    const query = input.query as string;
    const tavilyApiKey = process.env.TAVILY_API_KEY;

    if (!tavilyApiKey) {
      return {
        success: false,
        content: "Web search is not configured (missing TAVILY_API_KEY).",
        metadata: { query, found: 0 },
      };
    }

    const res = await fetch("https://api.tavily.com/search", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        api_key: tavilyApiKey,
        query,
        search_depth: "basic",
        max_results: 5,
      }),
    });

    if (!res.ok) {
      return {
        success: false,
        content: `Web search failed: ${res.status}`,
        metadata: { query, found: 0 },
      };
    }

    const data = await res.json();
    const results = data.results || [];

    if (results.length === 0) {
      return {
        success: true,
        content: `No web results found for "${query}"`,
        metadata: { query, found: 0 },
      };
    }

    const formatted = results
      .map(
        (r: { title: string; url: string; content: string }, i: number) =>
          `[${i + 1}] ${r.title}\n${r.url}\n${r.content?.slice(0, 200)}...`
      )
      .join("\n\n");

    return {
      success: true,
      content: `Found ${results.length} web results for "${query}":\n\n${formatted}`,
      metadata: { query, found: results.length },
    };
  },
};
