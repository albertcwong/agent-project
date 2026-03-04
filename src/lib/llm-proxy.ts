import { createOpenAI } from "@ai-sdk/openai";

const baseURL = process.env.LLM_PROXY_URL || "http://localhost:8000";
const apiKey = process.env.LLM_PROXY_API_KEY || "dummy";
const provider = process.env.LLM_PROXY_PROVIDER || "openai";

export const llmProxy = createOpenAI({
  baseURL: `${baseURL.replace(/\/$/, "")}/v1`,
  apiKey,
  headers: {
    "x-provider": provider,
  },
});

export function createProxyWithProvider(p: string) {
  return createOpenAI({
    baseURL: `${baseURL.replace(/\/$/, "")}/v1`,
    apiKey,
    headers: {
      "x-provider": p,
    },
  });
}
