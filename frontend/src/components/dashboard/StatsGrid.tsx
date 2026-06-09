"use client";
import { LucideIcon } from "@/components/ui/Icon";
import type { RiskReport, RiskSeverity } from "@/lib/types";
import { useTranslations } from "next-intl";

interface StatCardProps {
  icon: string;
  color: string;
  label: string;
  value: string | number;
  sub?: string;
}

function StatCard({ icon, color, label, value, sub }: StatCardProps) {
  return (
    <div className="bg-white/80 backdrop-blur-sm p-4 rounded-md border border-slate-200 flex items-center gap-3 transition-all duration-300 hover:shadow-lg hover:shadow-slate-200/40">
      <div
        className="w-10 h-10 rounded-xl flex items-center justify-center shrink-0 shadow-inner"
        style={{ backgroundColor: color + "10", color: color }}
      >
        <LucideIcon name={icon} size={20} />
      </div>

      <div className="flex-1 min-w-0">
        <div className="text-[10px] font-medium  tracking-wider text-slate-400 mb-0.5">
          {label}
        </div>
        <div className="text-sm font-bold text-[#202020] truncate leading-tight">
          {value}
        </div>
        {sub && (
          <div className="text-[10px] font-medium text-slate-400 mt-1 flex items-center gap-1">
            <span className="w-1 h-1 rounded-full bg-slate-200" />
            {sub}
          </div>
        )}
      </div>
    </div>
  );
}

export function StatsGrid({ report }: { report: RiskReport }) {
  const t = useTranslations("Dashboard.stats");
  const ts = useTranslations("Severity");
  const counts = report.risks.reduce(
    (acc, r) => {
      acc[r.severity as RiskSeverity] =
        (acc[r.severity as RiskSeverity] ?? 0) + 1;
      return acc;
    },
    {} as Record<RiskSeverity, number>,
  );

  const subSummary = [
    counts.High
      ? t("severity_counts", { count: counts.High, severity: ts("high") })
      : null,
    counts.Medium
      ? t("severity_counts", { count: counts.Medium, severity: ts("medium") })
      : null,
    counts.Low
      ? t("severity_counts", { count: counts.Low, severity: ts("low") })
      : null,
  ]
    .filter(Boolean)
    .join(" • ");
  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 pb-3">
      <StatCard
        icon="file-text"
        color="#67a1ff"
        label={t("contract_type")}
        value={report.contract_type}
      />

      <StatCard
        icon="shield-alert"
        color={report.overall_risk === "High" ? "#ef4444" : "#f59e0b"}
        label={t("overall_assessment")}
        value={report.overall_risk}
      />

      <StatCard
        icon="list-checks"
        color="#8b5cf6"
        label={t("findings")}
        value={`${report.risks.length} ${t("detected")}`}
        sub={subSummary}
      />

      <StatCard
        icon="message-square"
        color="#10b981"
        label={t("final_advice")}
        value={report.final_recommendation}
      />
    </div>
  );
}
