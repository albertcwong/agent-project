import OpenAI from "openai";
import { NextResponse } from "next/server";

export const maxDuration = 300;

const IMAGE_EXT = /\.(png|jpe?g|gif|webp)$/i;
const TEXT_EXT = /\.(txt|csv|json|md|log)$/i;

function buildUserContent(
  text: string,
  attachments?: { filename: string; contentBase64: string }[]
): string | OpenAI.Chat.Completions.ChatCompletionContentPart[] {
  if (!attachments?.length) return text;

  const parts: OpenAI.Chat.Completions.ChatCompletionContentPart[] = [{ type: "text", text }];
  for (const a of attachments) {
    const ext = a.filename.split(".").pop()?.toLowerCase() ?? "";
    if (IMAGE_EXT.test(a.filename)) {
      const mime = ext === "png" ? "image/png" : ext === "gif" ? "image/gif" : ext === "webp" ? "image/webp" : "image/jpeg";
      parts.push({ type: "image_url", image_url: { url: `data:${mime};base64,${a.contentBase64}` } });
    } else if (TEXT_EXT.test(a.filename)) {
      try {
        const decoded = Buffer.from(a.contentBase64, "base64").toString("utf-8");
        parts.push({ type: "text", text: `\n\n[File: ${a.filename}]\n${decoded}` });
      } catch {
        parts.push({ type: "text", text: `\n\n[File: ${a.filename} - could not decode]` });
      }
    }
  }
  return parts;
}

async function getEndorHeaders(baseUrl: string, apiKey: string, provider: string): Promise<Record<string, string>> {
  const headers: Record<string, string> = { "x-provider": provider };
  if (provider !== "endor") return headers;
  try {
    const r = await fetch(`${baseUrl}/auth/endor/token`, {
      headers: apiKey !== "dummy" ? { "x-api-key": apiKey } : {},
    });
    if (!r.ok) return headers;
    const data = await r.json();
    if (data?.token) headers["x-endor-token"] = data.token;
  } catch {
    /* ignore */
  }
  return headers;
}

export async function POST(req: Request) {
  try {
    const { messages, model, provider, attachments } = await req.json();
    const baseUrl = (process.env.LLM_PROXY_URL || "http://localhost:8000").replace(/\/$/, "");
    const apiKey = process.env.LLM_PROXY_API_KEY || "dummy";
    const defaultProvider = process.env.LLM_PROXY_PROVIDER || "openai";
    const p = provider || defaultProvider;
    const defaultHeaders = await getEndorHeaders(baseUrl, apiKey, p);

    const client = new OpenAI({
      baseURL: `${baseUrl}/v1`,
      apiKey,
      defaultHeaders,
    });

    const filtered = (messages || []).filter((m: { role?: string; content?: string }) => m.role && m.content);
    const lastUser = filtered.filter((m: { role?: string }) => m.role === "user").pop();
    const processed = filtered.slice(0, -1);
    if (lastUser && lastUser.role === "user") {
      const content = buildUserContent(lastUser.content || "", attachments);
      processed.push({ role: "user", content });
    } else if (filtered.length) {
      processed.push(...filtered.slice(-1));
    }

    const stream = await client.chat.completions.create({
      model: model || "gpt-4",
      messages: [
        { role: "system", content: "Respond in a professional tone. Do not use emojis. Use clear, structured formatting." },
        ...processed,
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
    const msg =
      err instanceof Error && (err.message === "Failed to fetch" || err.message === "fetch failed")
        ? "Could not reach the LLM proxy. Check LLM_PROXY_URL (default http://localhost:8000). In Docker, use host.docker.internal."
        : err instanceof Error
          ? err.message
          : "Chat failed";
    return NextResponse.json({ error: msg }, { status: 500 });
  }
}
