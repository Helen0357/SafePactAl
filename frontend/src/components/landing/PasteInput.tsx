"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { useTranslations } from "next-intl";
import { useState } from "react";

interface PasteInputProps {
  onSubmit: (text: string) => void;
  isLoading: boolean;
}

export function PasteInput({ onSubmit, isLoading }: PasteInputProps) {
  const [text, setText] = useState("");
  const t = useTranslations("PasteInput");

  const handleSubmit = () => {
    const trimmed = text.trim();
    if (trimmed.length < 50) return;
    onSubmit(trimmed);
  };

  const charCount = text.length;
  const canSubmit = charCount >= 50 && !isLoading;

  return (
    <div className="flex flex-col !bg-white rounded-md overflow-hidden border border-slate-200 shadow-sm   transition-all duration-500 relative z-30">
      <textarea
        className="w-full min-h-[280px] p-8 text-slate-700 bg-transparent outline-none resize-none text-base leading-relaxed placeholder:text-slate-300"
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder={t("placeholder")}
        disabled={isLoading}
      />

      <div className="flex items-center justify-between p-4 bg-slate-50/80 border-t border-slate-50">
        <div className="flex items-center gap-4">
          <div className="flex gap-2 items-center">
            <span
              className={`text-xs font-bold  ${charCount < 50 ? "text-[#656565]" : "text-[#00e340]"}`}
            >
              {t("char_count")} :
            </span>
            <span className="text-sm  font-bold text-slate-600">
              {charCount.toLocaleString()}
            </span>
          </div>

          {charCount > 0 && charCount < 50 && (
            <div className="flex items-center gap-2 px-3 py-1 bg-amber-50 rounded-lg animate-in fade-in slide-in-from-left-2">
              <LucideIcon name="info" size={14} className="text-amber-500" />
              <span className="text-[11px] font-bold text-amber-700">
                {t("min_chars_warning")}
              </span>
            </div>
          )}
        </div>

        <button
          className={`!rounded-full px-8 py-3 !bg-[#67a1ff] shadow-lg text-sm shadow-blue-100 transition-all ${!canSubmit ? "opacity-30 grayscale" : "hover:scale-105 active:scale-95 text-white"}`}
          onClick={handleSubmit}
          disabled={!canSubmit}
        >
          {isLoading ? (
            <div className="flex items-center gap-2">
              <LucideIcon name="loader" size={18} className="animate-spin" />
              {t("analyzing")}
            </div>
          ) : (
            <div className="flex items-center gap-2">
              <LucideIcon name="search" size={18} />
              {t("analyze_button")}
            </div>
          )}
        </button>
      </div>
    </div>
  );
}
