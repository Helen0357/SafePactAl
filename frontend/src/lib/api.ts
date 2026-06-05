import axios from "axios";
import type {
  AnalyzeResponse,
  GenerateMessageRequest,
  GenerateMessageResponse,
} from "./types";

// API base URL. Accepts NEXT_PUBLIC_API_BASE_URL (preferred) or the legacy
// NEXT_PUBLIC_API_URL, falling back to local dev.
export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "http://localhost:8001";

const api = axios.create({
  baseURL: API_BASE_URL,
  timeout: 120_000,
});

api.interceptors.request.use((config) => {
  if (typeof document !== "undefined") {
    const locale = document.documentElement.lang || "en";
    config.headers["X-Language"] = locale;
  }
  return config;
});

export async function analyzeContract(
  file?: File,
  text?: string,
): Promise<AnalyzeResponse> {
  const form = new FormData();
  if (file) form.append("file", file);
  if (text) form.append("text", text);
  const { data } = await api.post<AnalyzeResponse>(
    "/api/contracts/analyze",
    form,
  );
  return data;
}

export async function generateMessage(
  req: GenerateMessageRequest,
): Promise<GenerateMessageResponse> {
  const { data } = await api.post<GenerateMessageResponse>(
    "/api/actions/generate-message",
    req,
  );
  return data;
}

export async function setActiveClause(
  sessionId: string,
  clauseId: string,
): Promise<void> {
  await api.post("/api/session/active-clause", {
    session_id: sessionId,
    active_clause_id: clauseId,
  });
}

export { api };
