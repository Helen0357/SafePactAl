"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { useTranslations } from "next-intl";

interface SearchInputProps {
  value: string;
  onChange: (v: string) => void;
}

export function SearchInput({ value, onChange }: SearchInputProps) {
  const t = useTranslations("Dashboard.filters");

  return (
    <div className="search !bg-white border rounded-sm">
      <LucideIcon name="search" size={17} />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("search_placeholder")}
        aria-label="Search risks"
        className=""
      />
      {value && (
        <button
          className="search-clear"
          onClick={() => onChange("")}
          aria-label="Clear search"
        >
          <LucideIcon name="x" size={14} />
        </button>
      )}
    </div>
  );
}
