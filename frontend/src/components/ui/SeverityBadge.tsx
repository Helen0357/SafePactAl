"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { SEVERITY_META } from "@/lib/types";
import { useTranslations } from "next-intl";

interface SeverityBadgeProps {
  severity: string;
  label?: string;
}

export function SeverityBadge({ severity, label }: SeverityBadgeProps) {
  const t = useTranslations("Severity");

  const meta = SEVERITY_META[severity] ?? SEVERITY_META["Low"];
  const cssKey = meta.cssKey;
  const translatedLabel = t(severity.toLowerCase() as any);
  const riskSuffix = t("risk_suffix");
  return (
    <span className={`pill pill-${cssKey} rounded-xs`}>
      <LucideIcon name={meta.icon} size={14} />
      {/* {label ?? `${meta.label} risk`} */}
      {label ?? `${translatedLabel} ${riskSuffix}`}
    </span>
  );
}
