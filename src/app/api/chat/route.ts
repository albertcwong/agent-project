import { createOpenAI } from "@ai-sdk/openai";
import { streamText } from "ai";

export const maxDuration = 300;

export async function POST(req: Request) {
  try {
    const { messages, model, provider } = await req.json();

    const baseUrl = process.env.LLM_PROXY_URL || "http://localhost:8000";
    const apiKey = process.env.LLM_PROXY_API_KEY || "dummy";
    const defaultProvider = process.env.LLM_PROXY_PROVIDER || "openai";

    const client = createOpenAI({
      baseURL: `${baseUrl.replace(/\/$/, "")}/v1`,
      apiKey,
      headers: {
        "x-provider": provider || defaultProvider,
      },
    });

    const result = streamText({
      model: client.chat(model || "gpt-4"),
      messages,
      system: "Respond in a professional tone. Do not use emojis. Use clear, structured formatting.",
    });

    return result.toTextStreamResponse();
  } catch (err) {
    console.error("Chat API error:", err);
    return Response.json(
      { error: err instanceof Error ? err.message : "Chat failed" },
      { status: 500 }
    );
  }
}
