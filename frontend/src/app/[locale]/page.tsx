"use client";
import { useState, useCallback } from "react";
import { useRouter } from "@/i18n/routing";
import { Nav } from "@/components/Nav";
import { Dropzone } from "@/components/landing/Dropzone";
import { PasteInput } from "@/components/landing/PasteInput";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Disclaimer } from "@/components/ui/Disclaimer";
import { Toast } from "@/components/ui/Toast";
import { LucideIcon } from "@/components/ui/Icon";
import { analyzeContract } from "@/lib/api";
import { useStore } from "@/store/useStore";
import { SAMPLE_CONTRACT } from "@/lib/sampleContract";
import type { ToastData } from "@/lib/types";
import { useTranslations } from "next-intl";

type UploadTab = "file" | "paste";

export default function LandingPage() {
  const router = useRouter();
  const { setSession, addDebugLine } = useStore();
  const t = useTranslations("Landing");

  const [tab, setTab] = useState<UploadTab>("file");
  const [isLoading, setIsLoading] = useState(false);
  const [progress, setProgress] = useState(0);
  const [toast, setToast] = useState<ToastData | null>(null);

  const showToast = useCallback((t: ToastData) => {
    setToast(t);
    setTimeout(() => setToast(null), 3000);
  }, []);

  const fakeProgress = useCallback(() => {
    setProgress(0);
    let p = 0;
    const interval = setInterval(() => {
      p += Math.random() * 12 + 5;
      if (p >= 92) {
        clearInterval(interval);
        p = 92;
      }
      setProgress(Math.round(p));
    }, 300);
    return interval;
  }, []);

  const runAnalysis = useCallback(
    async (file?: File, text?: string) => {
      setIsLoading(true);
      const ticker = fakeProgress();
      addDebugLine(
        "info",
        file ? `Uploading: ${file.name}` : "Analyzing pasted contract text…",
      );

      try {
        const result = await analyzeContract(file, text);
        clearInterval(ticker);
        setProgress(100);

        setSession(result.session_id, result.risk_report);
        addDebugLine(
          "agent",
          `Analysis complete — ${result.risk_report.risks.length} risks detected`,
        );
        addDebugLine(
          "tool",
          `risk.classify() → overall: ${result.risk_report.overall_risk}`,
        );

        setTimeout(() => router.push("/dashboard"), 300);
      } catch (err: unknown) {
        clearInterval(ticker);
        setProgress(0);
        setIsLoading(false);

        const message =
          err instanceof Error
            ? err.message
            : "Analysis failed. Is the backend running?";
        addDebugLine("error", `Analysis failed: ${message}`);
        showToast({
          kind: "error",
          title: "Analysis failed",
          body: message,
        });
      }
    },
    [fakeProgress, setSession, addDebugLine, router, showToast],
  );

  const handleFile = useCallback(
    (file: File) => runAnalysis(file, undefined),
    [runAnalysis],
  );

  const handlePaste = useCallback(
    (text: string) => runAnalysis(undefined, text),
    [runAnalysis],
  );

  const handleSample = useCallback(
    () => runAnalysis(undefined, SAMPLE_CONTRACT),
    [runAnalysis],
  );

  return (
    <div className="app overflow-hidden">
      <div className="fixed top-0 left-0 w-full h-full pointer-events-none opacity-50">
        <div className="absolute top-[-6%] left-[-9%] w-[40%] h-[40%] bg-[#7aadff64] rounded-full blur-[100px]"></div>
        <div className="absolute bottom-[-10%] right-[-10%] w-[30%] h-[30%] bg-[#67a1ff46] rounded-full blur-[120px]"></div>
      </div>{" "}
      <Nav />
      <main className="wrap landing">
        {/* Hero Section */}
        <div className="text-center mb-10 space-y-2">
          <span className="inline-block px-4 py-1.5 rounded-full bg-[#67a1ff10] text-[#333] text-xs font-medium tracking-widest animate-fade-in rtl:mb-3">
            {t("hero.eyebrow")}
          </span>

          <h1 className="text-5xl ltr:md:text-6xl rtl:md:text-5xl font-black text-[#252525] ltr:tracking-tight ltr:leading-[1.1] flex flex-col rtl:gap-5">
            {t("hero.title_main")} <br />
            <span className=" text-[#9ac1ff] ">
              {t("hero.title_highlight")}
            </span>
          </h1>

          <p className="max-w-xl mx-auto text-sm ltr:pt-2 rtl:pt-6 text-[#333] leading-relaxed">
            {t("hero.description")}
          </p>
        </div>

        <div className="max-w-5xl mx-auto fade-up">
          <div className="flex p-1.5 bg-white rounded-full shadow-sm mb-5 max-w-xs mx-auto border border-slate-200">
            <button
              className={`flex-1 flex items-center justify-center gap-2 py-2 !rounded-full text-sm font-medium transition-all ${tab === "file" ? "bg-[#7aadff] text-white shadow-md" : "text-slate-400 hover:text-slate-600"}`}
              onClick={() => setTab("file")}
            >
              <LucideIcon name="upload-cloud" size={16} />
              {t("tabs.file")}
            </button>
            <button
              className={`flex-1 flex items-center justify-center gap-2 py-2 !rounded-full text-sm font-medium transition-all ${tab === "paste" ? "bg-[#7aadff] text-white shadow-md" : "text-slate-400 hover:text-slate-600"}`}
              onClick={() => setTab("paste")}
            >
              <LucideIcon name="clipboard" size={16} />
              {t("tabs.paste")}
            </button>
          </div>

          {tab === "file" ? (
            <Dropzone
              onFile={handleFile}
              onSample={handleSample}
              isLoading={isLoading}
              progress={progress}
            />
          ) : (
            <PasteInput onSubmit={handlePaste} isLoading={isLoading} />
          )}

          <div className="privacy-note">
            <LucideIcon name="lock" size={15} color="#64748b" />
            <span className="text-slate-500">{t("privacy_note")}</span>
          </div>
        </div>

        <section className="landing-section" id="how_it_work">
          <div className="text-center mb-12">
            <h2 className="text-4xl font-bold text-[#252525]">
              {t("how_it_works")}
            </h2>
            <div className="h-1.5 w-14 bg-[#7aadff] mx-auto mt-4 rounded-full"></div>
          </div>
          <HowItWorks />
        </section>
      </main>
      <Disclaimer />
      <Toast toast={toast} />
    </div>
  );
}
