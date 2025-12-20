import Anthropic from "@anthropic-ai/sdk";
import { NextRequest } from "next/server";
import { cookies } from "next/headers";
import { getToolDefinitions, executeTool, ToolContext } from "./tools";

// Hardcoded project ID for testing - point to an existing project with documents
const TEST_PROJECT_ID = "01100eb0-9581-42fe-8446-aea1298753b4";

// Backend API base - use internal Docker network URL for server-side calls
const API_BASE =
  process.env.API_URL_INTERNAL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8000";

// Get tool definitions for Claude
const tools = getToolDefinitions();

// Message type for the conversation
interface Message {
  role: "user" | "assistant";
  content: string;
}

export async function POST(request: NextRequest) {
  const encoder = new TextEncoder();

  // Get cookies from request to forward to backend
  const cookieStore = await cookies();
  const cookieHeader = cookieStore
    .getAll()
    .map((c) => `${c.name}=${c.value}`)
    .join("; ");

  // Create a readable stream for SSE
  const stream = new ReadableStream({
    async start(controller) {
      try {
        const body = await request.json();
        const { messages } = body as {
          messages: Message[];
        };

        if (!cookieHeader) {
          controller.enqueue(
            encoder.encode(`data: ${JSON.stringify({ type: "error", error: "Not authenticated" })}\n\n`)
          );
          controller.close();
          return;
        }

        const anthropic = new Anthropic({
          apiKey: process.env.ANTHROPIC_API_KEY,
        });

        // Convert messages to Anthropic format
        let anthropicMessages: Anthropic.MessageParam[] = messages.map((m) => ({
          role: m.role,
          content: m.content,
        }));

        const systemPrompt = `You are a helpful research assistant with access to the user's documents and the web.
Use your tools to find information and answer questions accurately.
When searching documents, use specific keywords.
Always cite your sources when providing information from documents or web searches.
Provide hyperlinks whenever possible. 
Use markdown formatting for hyperlinks.
Keep responses brief unless the user indicates they want a more verbose response.`;

        let continueLoop = true;
        const maxIterations = 10;
        let iteration = 0;

        while (continueLoop && iteration < maxIterations) {
          iteration++;

          // Call Claude with streaming
          const response = await anthropic.messages.create({
            model: "claude-sonnet-4-20250514",
            max_tokens: 4096,
            system: systemPrompt,
            tools,
            messages: anthropicMessages,
            stream: true,
          });

          let currentText = "";
          let toolUseBlocks: Array<{
            id: string;
            name: string;
            input: Record<string, unknown>;
          }> = [];
          let currentToolUse: {
            id: string;
            name: string;
            inputJson: string;
          } | null = null;

          // Buffer for sentence-based streaming
          let textBuffer = "";

          // Helper to find the last sentence boundary in text
          // Returns the index after the boundary, or -1 if no boundary found
          const findSentenceBoundary = (text: string): number => {
            // Look for sentence endings: ". ", "! ", "? ", or paragraph breaks "\n\n"
            // Also handle markdown list items "\n- " and numbered lists "\n1. "
            const patterns = [
              /\.\s+/g,      // Period followed by whitespace
              /!\s+/g,       // Exclamation followed by whitespace
              /\?\s+/g,      // Question mark followed by whitespace
              /\n\n/g,       // Paragraph break
              /\n[-*]\s/g,   // Markdown list item
              /\n\d+\.\s/g,  // Numbered list item
              /:\n/g,        // Colon followed by newline (often precedes lists)
            ];

            let lastBoundary = -1;
            for (const pattern of patterns) {
              let match;
              while ((match = pattern.exec(text)) !== null) {
                const boundaryEnd = match.index + match[0].length;
                if (boundaryEnd > lastBoundary) {
                  lastBoundary = boundaryEnd;
                }
              }
            }
            return lastBoundary;
          };

          // Helper to emit buffered text
          const flushBuffer = (force = false) => {
            if (!textBuffer) return;

            if (force) {
              // Emit everything remaining
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify({
                    type: "text",
                    content: textBuffer,
                  })}\n\n`
                )
              );
              textBuffer = "";
              return;
            }

            // Find the last sentence boundary
            const boundaryIndex = findSentenceBoundary(textBuffer);
            if (boundaryIndex > 0) {
              // Emit up to and including the boundary
              const toEmit = textBuffer.slice(0, boundaryIndex);
              textBuffer = textBuffer.slice(boundaryIndex);
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify({
                    type: "text",
                    content: toEmit,
                  })}\n\n`
                )
              );
            }
          };

          // Process the stream
          for await (const event of response) {
            if (event.type === "content_block_start") {
              if (event.content_block.type === "tool_use") {
                // Flush any remaining text before tool call
                flushBuffer(true);
                currentToolUse = {
                  id: event.content_block.id,
                  name: event.content_block.name,
                  inputJson: "",
                };
                // Emit tool call start
                controller.enqueue(
                  encoder.encode(
                    `data: ${JSON.stringify({
                      type: "tool_call_start",
                      tool: event.content_block.name,
                      id: event.content_block.id,
                    })}\n\n`
                  )
                );
              }
            } else if (event.type === "content_block_delta") {
              if (event.delta.type === "text_delta") {
                currentText += event.delta.text;
                textBuffer += event.delta.text;
                // Try to emit complete sentences
                flushBuffer();
              } else if (event.delta.type === "input_json_delta" && currentToolUse) {
                currentToolUse.inputJson += event.delta.partial_json;
              }
            } else if (event.type === "content_block_stop") {
              if (currentToolUse) {
                try {
                  const input = JSON.parse(currentToolUse.inputJson || "{}");
                  toolUseBlocks.push({
                    id: currentToolUse.id,
                    name: currentToolUse.name,
                    input,
                  });
                  // Emit tool call with parsed input
                  controller.enqueue(
                    encoder.encode(
                      `data: ${JSON.stringify({
                        type: "tool_call",
                        tool: currentToolUse.name,
                        id: currentToolUse.id,
                        input,
                      })}\n\n`
                    )
                  );
                } catch {
                  console.error("Failed to parse tool input JSON");
                }
                currentToolUse = null;
              } else {
                // Text block stopped - flush remaining buffer
                flushBuffer(true);
              }
            } else if (event.type === "message_stop") {
              // Message complete - ensure buffer is flushed
              flushBuffer(true);
            }
          }

          // Check if we need to execute tools
          if (toolUseBlocks.length > 0) {
            // Build the assistant message with tool use
            const assistantContent: Anthropic.ContentBlockParam[] = [];
            if (currentText) {
              assistantContent.push({ type: "text", text: currentText });
            }
            for (const tool of toolUseBlocks) {
              assistantContent.push({
                type: "tool_use",
                id: tool.id,
                name: tool.name,
                input: tool.input,
              });
            }

            // Add assistant message to conversation
            anthropicMessages.push({
              role: "assistant",
              content: assistantContent,
            });

            // Execute tools and collect results
            const toolResults: Anthropic.ToolResultBlockParam[] = [];
            for (const tool of toolUseBlocks) {
              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify({
                    type: "tool_executing",
                    tool: tool.name,
                    id: tool.id,
                  })}\n\n`
                )
              );

              const toolContext: ToolContext = {
                cookieHeader,
                projectId: TEST_PROJECT_ID,
                apiBase: API_BASE,
              };
              const result = await executeTool(tool.name, tool.input, toolContext);

              controller.enqueue(
                encoder.encode(
                  `data: ${JSON.stringify({
                    type: "tool_result",
                    tool: tool.name,
                    id: tool.id,
                    success: result.success,
                    metadata: result.metadata,
                  })}\n\n`
                )
              );

              toolResults.push({
                type: "tool_result",
                tool_use_id: tool.id,
                content: result.content,
              });
            }

            // Add tool results to conversation
            anthropicMessages.push({
              role: "user",
              content: toolResults,
            });

            // Send a paragraph break before the next iteration's text
            controller.enqueue(
              encoder.encode(
                `data: ${JSON.stringify({
                  type: "text",
                  content: "\n\n",
                })}\n\n`
              )
            );

            // Continue the loop to let Claude respond to tool results
          } else {
            // No tool calls, we're done
            continueLoop = false;
          }
        }

        // Send done event
        controller.enqueue(encoder.encode(`data: ${JSON.stringify({ type: "done" })}\n\n`));
        controller.close();
      } catch (error) {
        console.error("Agent error:", error);
        controller.enqueue(
          encoder.encode(
            `data: ${JSON.stringify({
              type: "error",
              error: error instanceof Error ? error.message : "Unknown error",
            })}\n\n`
          )
        );
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
