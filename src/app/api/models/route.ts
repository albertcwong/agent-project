import { NextResponse } from "next/server";

const PROVIDERS = ["openai", "salesforce", "endor"] as const;

export async function GET() {
  const baseUrl = process.env.LLM_PROXY_URL || "http://localhost:8000";
  const apiKey = process.env.LLM_PROXY_API_KEY;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (apiKey) {
    headers["x-api-key"] = apiKey;
  }

  const results: Record<string, { id: string }[]> = {};

  await Promise.all(
    PROVIDERS.map(async (provider) => {
      try {
        const res = await fetch(
          `${baseUrl}/v1/models?provider=${provider}`,
          { headers }
        );
        if (!res.ok) {
          results[provider] = [];
          return;
        }
        const data = await res.json();
        const models = Array.isArray(data.data)
          ? data.data.map((m: { id: string }) => ({ id: m.id }))
          : [];
        results[provider] = models;
      } catch {
        results[provider] = [];
      }
    })
  );

  return NextResponse.json(results);
}
