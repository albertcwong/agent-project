import OpenAI from "openai";
import { NextResponse } from "next/server";

export const maxDuration = 300;

export async function POST(req: Request) {
  try {
    const { messages, model, provider } = await req.json();
    const baseUrl = (process.env.LLM_PROXY_URL || "http://localhost:8000").replace(/\/$/, "");
    const apiKey = process.env.LLM_PROXY_API_KEY || "dummy";
    const defaultProvider = process.env.LLM_PROXY_PROVIDER || "openai";

    const client = new OpenAI({
      baseURL: `${baseUrl}/v1`,
      apiKey,
      defaultHeaders: { "x-provider": provider || defaultProvider },
    });

    const stream = await client.chat.completions.create({
      model: model || "gpt-4",
      messages: [
        { role: "system", content: "Respond in a professional tone. Do not use emojis. Use clear, structured formatting." },
        ...(messages || []).filter((m: { role?: string; content?: string }) => m.role && m.content),
      ],
      stream: true,
    });

    const encoder = new TextEncoder();
    const readable = new ReadableStream({
      async start(controller) {
        try {
          for await (const chunk of stream) {
            const text = chunk.choices[0]?.delta?.content;
            if (text) controller.enqueue(encoder.encode(text));
          }
        } finally {
          controller.close();
        }
      },
    });

    return new Response(readable, {
      headers: { "Content-Type": "text/plain; charset=utf-8" },
    });
  } catch (err) {
    console.error("Chat API error:", err);
    return NextResponse.json(
      { error: err instanceof Error ? err.message : "Chat failed" },
      { status: 500 }
    );
  }
}
