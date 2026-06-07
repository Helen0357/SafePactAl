export type RiskSeverity = "High" | "Medium" | "Low";
export type OverallRisk = "High" | "Medium" | "Low" | "Minimal";

export interface RiskItem {
  id: string;
  title: string;
  severity: RiskSeverity;
  category: string;
  clause_text: string;
  simple_explanation: string;
  why_it_matters: string;
  question_to_ask: string;
  suggested_action: string;
}

export interface RiskReport {
  contract_type: string;
  overall_risk: OverallRisk;
  final_recommendation: string;
  summary: string;
  confidence: number;
  risks: RiskItem[];
  missing_information: string[];
  recommended_questions: string[];
}

export interface AnalyzeResponse {
  session_id: string;
  risk_report: RiskReport;
}

export interface DebugLine {
  kind: "agent" | "tool" | "info" | "error";
  text: string;
}

export type FilterTab = "all" | "high" | "medium" | "low";

export type MessageType = "clarification" | "negotiation" | "rejection" | "amendment_request";
export type MessageTone = "polite" | "firm" | "professional";
export type MessageFormat = "email" | "whatsapp";

export interface GenerateMessageRequest {
  session_id: string;
  clause_ids: string[];
  message_type: MessageType;
  tone: MessageTone;
  format: MessageFormat;
  extra_instruction?: string;
  language?: string; // 'ar' | 'en' — draft language (website language)
}

export interface GenerateMessageResponse {
  draft: string;
  session_id: string;
  clause_ids: string[];
  message_type: string;
  tone: string;
  format: string;
}

export interface ToastData {
  kind: "success" | "warning" | "error" | "info";
  icon?: string;
  title: string;
  body?: string;
}

export const SEVERITY_ORDER: Record<RiskSeverity, number> = {
  High: 0,
  Medium: 1,
  Low: 2,
};

export type VoiceStatus =
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "tool_running"
  | "draft_ready"
  | "error";

export interface TranscriptEntry {
  role: "user" | "agent";
  text: string;
  kind: "text" | "draft" | "error";
}

export const SEVERITY_META: Record<string, { label: string; icon: string; cssKey: string }> = {
  High:   { label: "High",   icon: "shield-alert",  cssKey: "high" },
  Medium: { label: "Medium", icon: "alert-circle",  cssKey: "medium" },
  Low:    { label: "Low",    icon: "check-circle",  cssKey: "low" },
  Minimal:{ label: "Minimal",icon: "check-circle",  cssKey: "low" },
};
