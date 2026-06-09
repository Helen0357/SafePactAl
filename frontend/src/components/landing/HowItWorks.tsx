"use client";
import { LucideIcon } from "@/components/ui/Icon";
import { useTranslations } from "next-intl";

export function HowItWorks() {
  const t = useTranslations("HowItWorks");
  const STEPS = [
    {
      title: t("steps.step1.title"),
      desc: t("steps.step1.desc"),
      visual: (
        <div className="relative w-full h-[11.5rem] bg-slate-50/50 rounded-lg border border-slate-100 flex items-center justify-center overflow-hidden group">
          <div className="absolute inset-0 opacity-[0.03] bg-[grid-linear-gradient(to_right,#67a1ff_1px,transparent_1px),grid-linear-gradient(to_bottom,#67a1ff_1px,transparent_1px)] bg-[size:20px_20px]" />

          <div className="relative w-32 h-[9.5rem] bg-white rounded-md shadow-2xl border border-slate-100 flex flex-col p-4 gap-3 transform group-hover:-translate-y-2 rotate-[-2deg] hover:rotate-[-5deg] transition-all duration-700 ease-out">
            <div className="w-full h-1 bg-slate-100 rounded-full overflow-hidden relative">
              <div className="absolute inset-0 bg-gradient-to-r from-transparent via-[#67a1ff] to-transparent w-1/2 animate-scan" />
            </div>
            {[...Array(4)].map((_, i) => (
              <div key={i} className="space-y-1">
                <div className="w-full h-1 bg-slate-50 rounded-full" />
                <div
                  className={`h-1 bg-slate-50 rounded-full ${i === 2 ? "w-2/3" : "w-full"}`}
                />
              </div>
            ))}
            <div className="absolute -bottom-2 -right-2 w-8 h-8 bg-[#67a1ff] rounded-lg shadow-lg flex items-center justify-center text-white  transition-transform delay-200">
              <LucideIcon name="check" size={18} />
            </div>
          </div>
        </div>
      ),
    },

    {
      title: t("steps.step2.title"),
      desc: t("steps.step2.desc"),
      visual: (
        <div className="relative w-full h-44 bg-slate-50/50 rounded-lg border border-slate-100 flex items-center justify-center p-6 group">
          <div className="w-full space-y-3">
            <div className="relative bg-white p-4 rounded-md border border-red-100 shadow-sm flex items-center gap-4 transform group-hover:translate-x-4 transition-transform duration-500">
              <div className="w-3 h-3 rounded-full bg-red-500 animate-ping absolute -top-1 -left-1" />
              <div className="w-2 h-7 bg-red-500 rounded-full" />
              <div className="flex-1 space-y-2">
                <div className="w-24 h-2 bg-red-100 rounded-full" />
                <div className="w-full h-1.5 bg-slate-50 rounded-full" />
              </div>
            </div>
            <div className="bg-white p-4 rounded-md border border-amber-100 shadow-sm flex items-center gap-4 transform group-hover:-translate-x-4 transition-transform duration-700 delay-75">
              <div className="w-2 h-7 bg-amber-400 rounded-full" />
              <div className="flex-1 space-y-2">
                <div className="w-20 h-2 bg-amber-50 rounded-full" />
                <div className="w-3/4 h-1.5 bg-slate-50 rounded-full" />
              </div>
              <LucideIcon
                name="alert-triangle"
                size={16}
                className="text-amber-500 opacity-40"
              />
            </div>
          </div>
          <div className="absolute inset-0 bg-[#67a1ff]/5 blur-3xl rounded-full opacity-0 group-hover:opacity-100 transition-opacity duration-1000" />
        </div>
      ),
    },
    {
      title: t("steps.step3.title"),
      desc: t("steps.step3.desc"),
      visual: (
        <div className="relative w-full h-44 bg-slate-50/50 rounded-lg border border-slate-100 flex items-center justify-center overflow-hidden group">
          <div className="absolute w-24 h-24 bg-[#67a1ff]/10 rounded-full animate-ping" />
          <div className="absolute w-16 h-16 bg-[#67a1ff]/20 rounded-full animate-pulse" />

          <div className="relative z-10 w-full px-6 space-y-3">
            <div className="bg-[#67a1ff] text-white p-3 rounded-2xl rounded-tr-none text-[11px] font-bold w-2/3 ltr:ml-auto shadow-xl shadow-blue-200 group-hover:-translate-y-2 transition-transform">
              {t("visuals.step3_user")}
            </div>
            <div className="bg-white/80 backdrop-blur-md p-3 rounded-2xl rounded-tl-none text-[11px] text-slate-600 font-medium w-4/5 flex items-center gap-3 border border-white shadow-lg group-hover:translate-y-2 transition-transform delay-100 rtl:mr-auto">
              <div className="w-6 h-6 rounded-lg bg-gradient-to-br from-[#67a1ff] to-blue-600 flex items-center justify-center shrink-0">
                <LucideIcon name="sparkles" size={12} color="#fff" />
              </div>
              <span className="animate-pulse whitespace-nowrap">
                {t("visuals.step3_agent")}
              </span>
              <div className="space-y-1.5 w-full">
                <div className="w-full h-1 bg-[#67a1ff]/20 rounded-full" />
                <div className="w-2/3 h-1 bg-[#67a1ff]/10 rounded-full" />
              </div>
            </div>
          </div>
        </div>
      ),
    },
  ];
  return (
    <div className="mt-14 space-y-8 pb-7 max-w-6xl mx-auto">
      {STEPS.map((step, i) => (
        <div
          key={i}
          className={`flex flex-col md:flex-row items-center gap-24 ${i % 2 !== 0 ? "md:flex-row-reverse" : ""} group`}
        >
          <div className="w-full md:w-1/2 space-y-3">
            <div className="flex items-center gap-3 pb-2">
              <span className="w-8 h-[1px] bg-[#7aadff]" />
              <span className="text-xs font-black uppercase tracking-[0.3em] text-[#7aadff]">
                {t("step_label")} 0{i + 1}
              </span>
            </div>
            <h3 className="text-3xl font-bold text-[#252525] tracking-tight leading-tight">
              {step.title}
            </h3>
            <p className="text-base text-slate-500 leading-relaxed max-w-md">
              {step.desc}
            </p>
          </div>

          <div className="w-full md:w-1/2">
            <div className="relative p-7 bg-white rounded-lg border border-[#efefef] shadow-sm transition-all duration-700 flex items-center justify-center min-h-[180px]">
              <div className="relative z-10 w-full">{step.visual}</div>
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}
