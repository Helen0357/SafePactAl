"use client";
import { Button } from "@/components/ui/Button";
import type { DebugLine, RiskItem } from "@/lib/types";
import { LucideIcon } from "../ui/Icon";
import { useTranslations } from "next-intl";

interface ActionBarProps {
  selectedCount: number;
  selectedRisks: RiskItem[];
  debugLines: DebugLine[];
  termOpen: boolean;
  onToggleTerm: () => void;
  onGenerateSelected: (risks: RiskItem[]) => void;
  onCallAgent: () => void;
}

export function ActionBar({
  selectedCount,
  selectedRisks,
  debugLines,
  termOpen,
  onToggleTerm,
  onGenerateSelected,
  onCallAgent,
}: ActionBarProps) {
  const t = useTranslations("ActionBar");
  return (
    <div className="fixed bottom-0 left-0 w-full flex flex-col items-center z-[100] pointer-events-none pb-8">
      {/* <div className="w-full max-w-4xl px-6 pointer-events-auto mb-4 transition-all duration-500">
        <DebugTerminal
          open={termOpen}
          onToggle={onToggleTerm}
          lines={debugLines}
        />
      </div> */}

      <div className="pointer-events-auto w-[40%] mx-auto flex justify-center">
        {selectedCount === 0 ? (
          <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
            <button
              className="!rounded-full px-10 py-4 flex items-center gap-2 text-sm text-white !bg-[#7aadff] shadow-[0_20px_50px_rgba(0,0,0,0.3)] hover:scale-105 transition-all"
              onClick={onCallAgent}
            >
              <LucideIcon name="phone" size={18} className="text-[#fff]" />
              <span className="font-bold tracking-tight">
                {t("talk_to_agent")}
              </span>
            </button>
          </div>
        ) : (
          <div className="w-full max-w-2xl px-4  ">
            <div className="bg-[#5e5e5e] backdrop-blur-2xl border border-white/10 rounded-full p-3 flex items-center justify-between shadow-[0_25px_60px_rgba(0,0,0,0.4)]">
              <div className="pl-5 flex items-center gap-3">
                <div className="w-8 h-8 rounded-full bg-[#fff]/20 flex items-center justify-center">
                  <span className="text-[#fff] text-sm font-black">
                    {selectedCount}
                  </span>
                </div>
                <p className="text-white text-sm font-bold tracking-tight">
                  {t("risks_selected", { count: selectedCount })}
                </p>
              </div>

              <div className="flex gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  className="!rounded-full font-bold !bg-white/10 flex gap-2 !border-white/10 !text-white !px-5"
                  onClick={() => onGenerateSelected(selectedRisks)}
                >
                  <LucideIcon
                    name="sparkles"
                    size={14}
                    className=" text-[#fff]"
                  />
                  {t("generate_message")}
                </Button>
                <button
                  className="!rounded-full flex items-center gap-2 !px-6 !bg-red-500 text-white text-xs !h-11 shadow-lg shadow-blue-500/20"
                  onClick={onCallAgent}
                >
                  <LucideIcon name="phone" size={14} className=" text-[#fff]" />
                  {t("call_agent")}
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
