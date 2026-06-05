"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { SeverityBadge } from "@/components/ui/SeverityBadge";
import { Button } from "@/components/ui/Button";
import type { RiskItem } from "@/lib/types";
import { useTranslations } from "next-intl";

interface RiskCardProps {
  risk: RiskItem;
  expanded: boolean;
  selected: boolean;
  onToggle: () => void;
  onSelect: () => void;
  onAsk: (risk: RiskItem) => void;
  onGenerate: (risk: RiskItem) => void;
}

// Final safety net: the backend normalizes blank fields, but if anything still
// arrives empty we never want to render an empty section in a risk card.
const ROW_FALLBACK =
  "This may create extra cost, responsibility, or uncertainty if not clarified.";

function coalesce(
  value: string | undefined | null,
  fallback = ROW_FALLBACK,
): string {
  return value && value.trim() ? value : fallback;
}

function RcRow({
  icon,
  label,
  children,
  fallback = ROW_FALLBACK,
}: {
  icon: string;
  label: string;
  children: string;
  fallback?: string;
}) {
  return (
    <div className="rc-row">
      <div className="rc-row-label">
        <LucideIcon name={icon} size={15} />
        {label}
      </div>
      <p>{coalesce(children, fallback)}</p>
    </div>
  );
}

export function RiskCard({
  risk,
  expanded,
  selected,
  onToggle,
  onSelect,
  onAsk,
  onGenerate,
}: RiskCardProps) {
  const t = useTranslations("RiskCard");

  const severityKey = risk.severity.toLowerCase();
  const preview =
    risk.simple_explanation.length > 120
      ? risk.simple_explanation.slice(0, 117) + "…"
      : risk.simple_explanation;
  return (
    <div
      className={`group mb-2 w-full rounded-md transition-all duration-500 overflow-hidden bg-white border  ${selected ? "border-[#67a1ff62] ring-4 ring-[#67a1ff0a]" : "border-slate-200"} riskcard riskcard-${severityKey}`}
    >
      <button
        className="w-full flex items-center gap-4 p-6 text-left"
        onClick={onToggle}
      >
        <div
          className={`w-12 h-12 rounded-2xl flex items-center justify-center shrink-0 ${
            severityKey === "high"
              ? "bg-red-50 text-red-500"
              : severityKey === "medium"
                ? "bg-amber-50 text-amber-500"
                : "bg-emerald-50 text-emerald-500"
          }`}
        >
          <LucideIcon
            name={
              severityKey === "high"
                ? "shield-alert"
                : severityKey === "medium"
                  ? "alert-triangle"
                  : "info"
            }
            size={24}
          />
        </div>

        <div className="flex-1">
          <div className="flex items-center gap-3 mb-1">
            <h3 className="text-[15px] font-bold text-[#363636] tracking-tight leading-snug">
              {risk.title}
            </h3>
            <span className="px-2 py-0.5 rounded-full bg-[#67a1ff]/10 text-[#7aadff] text-[10px] font-bold uppercase tracking-wider">
              {risk.category}
            </span>
          </div>
          {!expanded && (
            <p className="text-xs text-slate-500 line-clamp-1 rtl:text-right ltr:text-left ">
              {risk.simple_explanation}
            </p>
          )}
        </div>

        <div className="flex items-center gap-4">
          {selected && (
            <div className="w-6 h-6 rounded-full bg-[#67a1ff] flex items-center justify-center text-white">
              <LucideIcon name="check" size={14} />
            </div>
          )}
          <LucideIcon
            name="chevron-down"
            size={20}
            className={`text-slate-300 transition-transform duration-500 ${expanded ? "rotate-180" : ""}`}
          />
        </div>
      </button>

      {expanded && (
        <div className="px-6 pb-8 space-y-4 animate-in fade-in slide-in-from-top-4 duration-500">
          <div className="p-5 rounded-sm bg-slate-50/80 border border-slate-100 relative overflow-hidden">
            <div className="absolute top-0 ltr:right-0 rtl:left-0 p-3 opacity-5">
              <LucideIcon name="quote" size={28} />
            </div>
            <span className="text-[10px] font-black uppercase text-slate-500 tracking-widest block mb-3">
              {t("original_text")}
            </span>
            <p className="text-[13px] font-mono text-slate-600 leading-relaxed ">
              {risk.clause_text}
            </p>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-[#67a1ff]">
                <LucideIcon name="message-circle" size={16} />
                <span className="text-xs font-bold uppercase tracking-wider">
                  {t("plain_terms")}
                </span>
              </div>
              <p className="text-sm text-[#333] leading-relaxed">
                {risk.simple_explanation}
              </p>
            </div>
            <div className="space-y-2">
              <div className="flex items-center gap-2 text-amber-500">
                <LucideIcon name="alert-circle" size={16} />
                <span className="text-xs font-bold uppercase tracking-wider">
                  {t("why_it_matters")}
                </span>
              </div>
              <p className="text-sm text-[#333] leading-relaxed">
                {risk.why_it_matters}
              </p>
            </div>
          </div>

          <div className="pt-4 border-t border-slate-50 flex flex-wrap items-center justify-between gap-4">
            <div className="flex gap-2">
              <Button
                variant="secondary"
                size="sm"
                icon="mic"
                className="!rounded-full !bg-white !border-slate-200 !text-slate-600"
                onClick={() => onAsk(risk)}
              >
                {t("ask_agent")}
              </Button>
              <Button
                variant="secondary"
                size="sm"
                icon="sparkles"
                className="!rounded-full !bg-white !border-slate-200 !text-slate-600"
                onClick={() => onGenerate(risk)}
              >
                {t("generate_message")}
              </Button>
            </div>
            <button
              onClick={onSelect}
              className={`flex items-center gap-2 px-5 py-2 rounded-full text-sm font-medium transition-all ${selected ? "bg-[#67a1ff] text-white" : "bg-slate-100 text-slate-400 hover:bg-slate-100"}`}
            >
              <LucideIcon
                name={selected ? "check-circle" : "plus-circle"}
                size={16}
              />
              {selected ? t("selected") : t("select_action")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
