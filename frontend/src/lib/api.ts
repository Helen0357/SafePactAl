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

export async function setSelectedClauses(
  sessionId: string,
  clauseIds: string[],
): Promise<void> {
  await api.post("/api/session/selected-clauses", {
    session_id: sessionId,
    selected_clause_ids: clauseIds,
  });
}

export const REPORT_PDF_FILENAME = "ProtectMe_AI_Risk_Report.pdf";

/** Trigger a direct browser download for an in-memory blob (no server storage). */
function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  // Revoke after a tick so the download has started.
  setTimeout(() => window.URL.revokeObjectURL(url), 1000);
}

/**
 * Fetch the risk-report PDF for a session and download it directly.
 * Throws an axios error (with `.response.status`) on 404/409 so the caller can
 * show the right message. Nothing is stored anywhere.
 */
export async function downloadReportPdf(
  sessionId: string,
  language = "en",
): Promise<void> {
  const resp = await api.post(
    "/api/reports/download-pdf",
    { session_id: sessionId, language },
    { responseType: "blob" },
  );
  const blob = new Blob([resp.data], { type: "application/pdf" });
  triggerBlobDownload(blob, REPORT_PDF_FILENAME);
}

export { api };
