"use client";
import { useMemo, useState } from "react";
import { LucideIcon } from "@/components/ui/Icon";
import { RiskCard } from "@/components/dashboard/RiskCard";
import { SEVERITY_ORDER, type RiskItem, type FilterTab } from "@/lib/types";
import { useTranslations } from "next-intl";

interface RiskListProps {
  risks: RiskItem[];
  filter: FilterTab;
  search: string;
  selectedIds: string[];
  onToggleSelect: (id: string) => void;
  onAsk: (risk: RiskItem) => void;
  onGenerate: (risk: RiskItem) => void;
}

export function RiskList({
  risks,
  filter,
  search,
  selectedIds,
  onToggleSelect,
  onAsk,
  onGenerate,
}: RiskListProps) {
  const t = useTranslations("RiskList");

  const [expandedId, setExpandedId] = useState<string | null>(
    risks.length > 0 ? null : null,
  );

  const sorted = useMemo(
    () =>
      [...risks].sort(
        (a, b) =>
          (SEVERITY_ORDER[a.severity] ?? 3) - (SEVERITY_ORDER[b.severity] ?? 3),
      ),
    [risks],
  );

  const visible = useMemo(() => {
    return sorted.filter((r) => {
      if (filter !== "all" && r.severity.toLowerCase() !== filter) return false;
      if (search.trim()) {
        const q = search.toLowerCase();
        return (r.title + r.clause_text + r.simple_explanation + r.category)
          .toLowerCase()
          .includes(q);
      }
      return true;
    });
  }, [sorted, filter, search]);

  if (visible.length === 0) {
    return (
      <div className="empty flex flex-col justify-center items-center ">
        <LucideIcon name="search-x" size={48} color="#333" />
        <h3 className="font-bold">{t("empty_title")}</h3>
        <p className="text-slate-500">{t("empty_subtitle")}</p>
      </div>
    );
  }

  return (
    <div className="risklist w-full">
      {visible.map((r) => (
        <RiskCard
          key={r.id}
          risk={r}
          expanded={expandedId === r.id}
          selected={selectedIds.includes(r.id)}
          onToggle={() => setExpandedId(expandedId === r.id ? null : r.id)}
          onSelect={() => onToggleSelect(r.id)}
          onAsk={onAsk}
          onGenerate={onGenerate}
        />
      ))}
    </div>
  );
}
