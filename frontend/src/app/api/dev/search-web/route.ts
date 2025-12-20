import { NextRequest, NextResponse } from "next/server";

export async function POST(request: NextRequest) {
  try {
    const { query } = await request.json();

    if (!query) {
      return NextResponse.json({
        success: false,
        formattedContent: "No query provided",
        rawResponse: null,
        error: "No query provided",
      });
    }

    const tavilyApiKey = process.env.TAVILY_API_KEY;
    if (!tavilyApiKey) {
      return NextResponse.json({
        success: false,
        formattedContent: "Web search is not configured (missing TAVILY_API_KEY)",
        rawResponse: null,
        error: "Missing TAVILY_API_KEY",
      });
    }

    const res = await fetch("https://api.tavily.com/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        api_key: tavilyApiKey,
        query,
        search_depth: "basic",
        max_results: 5,
      }),
    });

    if (!res.ok) {
      return NextResponse.json({
        success: false,
        formattedContent: `Tavily API error: ${res.status}`,
        rawResponse: null,
        error: `HTTP ${res.status}`,
      });
    }

    const data = await res.json();
    const results = data.results || [];

    // Format like the tool does
    let formattedContent: string;
    if (results.length === 0) {
      formattedContent = `No web results found for "${query}"`;
    } else {
      const formatted = results
        .map(
          (r: { title: string; url: string; content: string }, i: number) =>
            `[${i + 1}] ${r.title}\n${r.url}\n${r.content?.slice(0, 200)}...`
        )
        .join("\n\n");
      formattedContent = `Found ${results.length} web results for "${query}":\n\n${formatted}`;
    }

    return NextResponse.json({
      success: true,
      formattedContent,
      rawResponse: data,
    });
  } catch (error) {
    return NextResponse.json({
      success: false,
      formattedContent: `Error: ${error instanceof Error ? error.message : "Unknown error"}`,
      rawResponse: null,
      error: error instanceof Error ? error.message : "Unknown error",
    });
  }
}
