"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { generateMessage } from "@/lib/api";
import type {
  DebugLine,
  MessageFormat,
  MessageTone,
  MessageType,
  RiskItem,
} from "@/lib/types";
import { useLocale, useTranslations } from "next-intl";
import { useCallback, useState } from "react";

interface MessagePanelProps {
  riskIds: string[];
  risks: RiskItem[];
  sessionId: string;
  onClose: () => void;
  onDebugLine: (kind: DebugLine["kind"], text: string) => void;
}

const TYPE_OPTIONS = [
  { value: "clarification", label: "Clarify", icon: "help-circle" },
  { value: "negotiation", label: "Negotiate", icon: "arrow-left-right" },
  { value: "rejection", label: "Reject", icon: "x-circle" },
  { value: "amendment_request", label: "Amend", icon: "file-edit" },
];

const TONE_OPTIONS = [
  { value: "polite", label: "Polite" },
  { value: "firm", label: "Firm" },
  { value: "professional", label: "Pro" },
];

const FORMAT_OPTIONS = [
  { value: "email", label: "Email", icon: "mail" },
  { value: "whatsapp", label: "WhatsApp", icon: "message-circle" },
];

export function MessagePanel({
  riskIds,
  risks,
  sessionId,
  onClose,
  onDebugLine,
}: MessagePanelProps) {
  const [messageType, setMessageType] = useState<MessageType>("clarification");
  const [tone, setTone] = useState<MessageTone>("professional");
  const [format, setFormat] = useState<MessageFormat>("email");
  const [draft, setDraft] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const t = useTranslations("MessagePanel");
  const locale = useLocale(); // website language → draft language

  const selectedRisks = risks.filter((r) => riskIds.includes(r.id));
  const renderOptionLabel = (val: string) => t(`options.${val}`);

  const callGenerate = useCallback(
    async (extraInstruction?: string) => {
      setIsLoading(true);
      onDebugLine(
        "info",
        `[GenerateMessage] language=${locale} format=${format} type=${messageType} tone=${tone}`,
      );
      try {
        const result = await generateMessage(
          {
            session_id: sessionId,
            clause_ids: riskIds,
            message_type: messageType,
            tone,
            format,
            extra_instruction: extraInstruction,
          },
          locale,
        );
        setDraft(result.draft);
        onDebugLine("agent", "Draft generated successfully");
      } catch (err) {
        onDebugLine("error", "Failed to generate message");
      } finally {
        setIsLoading(false);
      }
    },
    [sessionId, riskIds, messageType, tone, format, locale, onDebugLine],
  );

  const handleCopy = useCallback(async () => {
    await navigator.clipboard.writeText(draft);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }, [draft]);

  return (
    <div className="flex flex-col h-full bg-white overflow-x-hidden relative animate-in slide-in-from-right duration-500">
      <div className="p-4 px-6 border-b border-slate-50 flex items-center justify-between ">
        <div className="flex items-center gap-3">
          <div className="w-8 h-8 rounded-xs bg-gradient-to-br from-[#67a1ff] via-[#7aadff] to-cyan-500 flex items-center justify-center text-white shadow-lg shadow-blue-200">
            <LucideIcon name="sparkles" size={20} />
          </div>
          <div>
            <h2 className="text-base font-black text-[#2e2e2e] tracking-tight">
              {t("header_title")}
            </h2>
            <p className="text-[10px] text-slate-400 font-bold uppercase tracking-widest">
              {t("header_subtitle")}
            </p>
          </div>
        </div>
        <button
          onClick={onClose}
          className="p-2 hover:bg-slate-50 rounded-xl transition-all"
        >
          <LucideIcon name="x" size={20} className="text-zinc-500" />
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-6 space-y-5 scrollbar-hide">
        <section className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-bold   text-slate-500">
              {t("context")}
            </h3>
            <span className="text-[10px] px-2 py-0.5 rounded-full bg-slate-100 text-slate-500 font-bold">
              {t("risks_count", { count: riskIds.length })}
            </span>
          </div>
          <div className="flex flex-wrap gap-2">
            {selectedRisks.map((r) => (
              <div
                key={r.id}
                className="px-3 py-1.5 rounded-xl bg-slate-50 border border-slate-100 text-[11px] font-medium text-slate-600 flex items-center gap-2"
              >
                <div
                  className={`w-1.5 h-1.5 rounded-full ${r.severity === "High" ? "bg-red-400" : "bg-amber-400"}`}
                />
                {r.title}
              </div>
            ))}
          </div>
        </section>

        <section className="space-y-4">
          <div className="space-y-3">
            <label className="text-xs font-bold   text-slate-500">
              {t("goal_label")}
            </label>
            <div className="grid grid-cols-2 gap-2">
              {TYPE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setMessageType(opt.value as MessageType)}
                  className={`flex items-center gap-3 p-3 rounded-2xl border transition-all text-xs font-medium ${messageType === opt.value ? "border-[#7aadff] bg-[#67a1ff0a] text-[#7aadff]" : "border-slate-100 text-slate-500 hover:border-slate-200"}`}
                >
                  <LucideIcon name={opt.icon} size={14} />
                  {renderOptionLabel(opt.value)}
                </button>
              ))}
            </div>
          </div>

          <div className="grid grid-cols-2 gap-8">
            <div className="space-y-2">
              <label className="text-xs font-bold   text-slate-500">
                {t("tone_label")}
              </label>
              <div className="flex p-1 bg-slate-50 rounded-xs border border-slate-100">
                {TONE_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setTone(opt.value as MessageTone)}
                    className={`flex-1 py-1.5  rounded-2xl text-xs font-medium  transition-all ${tone === opt.value ? "bg-[#7aadff]/80  text-white" : "text-slate-500"}`}
                  >
                    {renderOptionLabel(opt.value)}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-2">
              <label className="text-xs font-bold   text-slate-500">
                {t("format_label")}
              </label>
              <div className="flex p-1 bg-slate-50 rounded-xs border border-slate-100">
                {FORMAT_OPTIONS.map((opt) => (
                  <button
                    key={opt.value}
                    onClick={() => setFormat(opt.value as MessageFormat)}
                    className={`flex-1 py-1.5 flex justify-center  rounded-2xl text-xs font-medium  transition-all ${format === opt.value ? "bg-[#7aadff]/80  text-white" : "text-slate-500"}`}
                  >
                    <LucideIcon name={opt.icon} size={14} />
                  </button>
                ))}
              </div>
            </div>
          </div>
        </section>

        <button
          className="!w-full !rounded-2xl py-3 px-6 bg-gradient-to-br from-[#67a1ff] via-[#7aadff] to-cyan-500 !text-white  text-sm font-bold flex justify-center text-center"
          onClick={() => callGenerate()}
          disabled={isLoading}
        >
          {isLoading ? (
            <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-white" />
          ) : draft ? (
            t("button_regenerate")
          ) : (
            t("button_generate")
          )}
        </button>

        {draft && (
          <div className="space-y-3 animate-in fade-in slide-in-from-top-4 duration-500 ">
            <div className="flex items-center justify-between ">
              <label className="text-xs font-bold   text-slate-500">
                {t("ai_response")}
              </label>
              <div className="flex gap-2">
                <div className="relative group">
                  <button
                    onClick={handleCopy}
                    className={`p-2 rounded-xl transition-all duration-300 ${copied ? "bg-emerald-500 text-white" : "bg-slate-100 text-slate-400 hover:text-[#67a1ff] hover:bg-[#67a1ff0a] "}`}
                  >
                    <LucideIcon name={copied ? "check" : "copy"} size={14} />
                  </button>
                  <span className="absolute bottom-full left-[20%] -translate-x-1/2 mb-2 px-3 py-1.5 bg-[#535353] text-white text-[10px] font-bold rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap shadow-xl">
                    {t("tooltips.copy")}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-[#535353]" />
                  </span>
                </div>
                <div className="relative group">
                  <button
                    onClick={() =>
                      callGenerate(
                        "Rewrite this message to be significantly shorter while keeping the key points.",
                      )
                    }
                    className="p-2 rounded-xl bg-slate-100 text-slate-400 hover:text-[#67a1ff] hover:bg-[#67a1ff0a] transition-all duration-300"
                  >
                    <LucideIcon name="minimize-2" size={15} />
                  </button>
                  <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 px-3 py-1.5 bg-[#535353] text-white text-[10px] font-bold rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap shadow-xl">
                    {t("tooltips.shorter")}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-[#535353]" />
                  </span>
                </div>

                <div className="relative group">
                  <button
                    onClick={() =>
                      callGenerate(
                        "Rewrite this message in a more formal, professional tone.",
                      )
                    }
                    className="p-2 rounded-xl bg-slate-100 text-slate-400 hover:text-[#67a1ff] hover:bg-[#67a1ff0a] transition-all duration-300"
                  >
                    <LucideIcon name="briefcase" size={15} />
                  </button>
                  <span className="absolute bottom-full ltr:left-[20%] rtl:left-[80%] -translate-x-1/2 mb-2 px-3 py-1.5 bg-[#535353] text-white text-[10px] font-bold rounded-lg opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap shadow-xl">
                    {t("tooltips.formal")}
                    <div className="absolute top-full left-1/2 -translate-x-1/2 border-4 border-transparent border-t-[#535353]" />
                  </span>
                </div>
              </div>
            </div>
            <div className="relative group">
              <textarea
                className="w-full bg-slate-50 border border-slate-100 rounded-sm p-4 text-sm text-[#333] leading-relaxed min-h-[180px] focus:ring-4 focus:ring-[#67a1ff0a] focus:border-[#67a1ff50] transition-all outline-none resize-none"
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
              />
            </div>
          </div>
        )}
      </div>

      <div className="p-3 bg-slate-50 border-t border-slate-200">
        <div className="flex gap-2 text-slate-500">
          <LucideIcon name="info" size={14} className="shrink-0 mt-0.5" />
          <p className="text-[10px] leading-relaxed font-medium">{t("text")}</p>
        </div>
      </div>
    </div>
  );
}
