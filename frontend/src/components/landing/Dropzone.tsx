"use client";
import { Button } from "@/components/ui/Button";
import { LucideIcon } from "@/components/ui/Icon";
import { useTranslations } from "next-intl";
import { useCallback, useRef, useState } from "react";

type DropzoneState = "idle" | "uploading" | "error";

interface DropzoneProps {
  onFile: (file: File) => void;
  onSample: () => void;
  isLoading: boolean;
  progress: number;
}

const ACCEPTED = /\.(pdf|docx|txt)$/i;

export function Dropzone({
  onFile,
  onSample,
  isLoading,
  progress,
}: DropzoneProps) {
  const [drag, setDrag] = useState(false);
  const [state, setState] = useState<DropzoneState>("idle");
  const inputRef = useRef<HTMLInputElement>(null);
  const t = useTranslations("Dropzone");

  const handleFile = useCallback(
    (file: File | undefined) => {
      if (!file) return;
      if (!ACCEPTED.test(file.name)) {
        setState("error");
        return;
      }
      setState("uploading");
      onFile(file);
    },
    [onFile],
  );

  const dzState = isLoading ? "uploading" : state;

  return (
    <div
      className={`relative group min-h-[300px] flex flex-col items-center justify-center p-6 rounded-md transition-all duration-500 border-2 border-dashed  shadow-sm
        ${drag ? "border-[#67a1ff] bg-[#67a1ff]/5 scale-[1.02]" : "border-slate-200 bg-white hover:border-[#67a1ff]/50"}
        ${dzState === "error" ? "border-red-200 bg-red-50/30" : ""}
      `}
      onDragOver={(e) => {
        e.preventDefault();
        setDrag(true);
      }}
      onDragLeave={() => setDrag(false)}
      onDrop={(e) => {
        e.preventDefault();
        setDrag(false);
        handleFile(e.dataTransfer.files[0]);
      }}
      onClick={() => {
        if (dzState !== "uploading") inputRef.current?.click();
      }}
    >
      <input
        ref={inputRef}
        type="file"
        accept=".pdf,.docx,.txt"
        className="hidden"
        onChange={(e) => handleFile(e.target.files?.[0])}
      />

      {dzState === "uploading" ? (
        <div className="w-full max-w-sm flex flex-col items-center animate-in fade-in zoom-in duration-300">
          <div className="w-20 h-20 rounded-3xl bg-[#67a1ff]/10 flex items-center justify-center mb-6 relative">
            <LucideIcon
              name="loader"
              size={32}
              className="text-[#67a1ff] animate-spin"
            />
            <div className="absolute inset-0 rounded-3xl border-2 border-[#67a1ff]  animate-spin" />
          </div>
          <h3 className="text-lg font-bold text-slate-900 mb-2">
            {t("uploading.title")}
          </h3>
          <p className="text-slate-500 text-sm mb-5 text-center">
            {t("uploading.subtitle")}
          </p>

          <div className="w-full bg-slate-100 h-2.5 rounded-full overflow-hidden shadow-inner">
            <div
              className="h-full bg-gradient-to-r from-[#67a1ff] to-[#7aadffc4] transition-all duration-500 ease-out rounded-full"
              style={{ width: `${progress}%` }}
            />
          </div>
          <span className="mt-3 text-xs font-bold text-[#67a1ff] bg-[#67a1ff]/10 px-3 py-1 rounded-full">
            {progress}% {t("uploading.processed")}
          </span>
        </div>
      ) : dzState === "error" ? (
        <div className="flex flex-col items-center text-center animate-in fade-in slide-in-from-bottom-4">
          <div className="w-16 h-16 rounded-2xl bg-red-50 text-red-500 flex items-center justify-center mb-4">
            <LucideIcon name="file-x" size={32} />
          </div>
          <h3 className="text-lg font-bold text-slate-900">
            {t("error.title")}
          </h3>
          <p className="text-sm text-slate-500 mt-1 max-w-[240px]">
            {t("error.subtitle")}
          </p>
          <Button
            variant="secondary"
            size="sm"
            className="mt-6 !rounded-full"
            onClick={(e) => {
              e.stopPropagation();
              setState("idle");
            }}
          >
            {t("error.button")}
          </Button>
        </div>
      ) : (
        <div className="flex flex-col items-center text-center animate-in fade-in duration-700">
          <div className=" rounded-[24px] text-[#7aadff8c] flex items-center justify-center mb-3 group-hover:scale-110 transition-transform duration-500">
            <LucideIcon name="upload" size={36} />
          </div>
          <h3 className="text-lg font-black text-[#252525] mb-1 tracking-tight">
            {t("idle.title")}
          </h3>
          <p className="text-slate-400 text-sm  mb-4 leading-relaxed">
            {t("idle.subtitle")}
          </p>

          <button
            className="!bg-[#67a1ff]  px-4 py-3 text-sm shadow-md shadow-blue-200 transition-shadow flex items-center gap-2 text-white !rounded-full"
            onClick={(e) => {
              e.stopPropagation();
              inputRef.current?.click();
            }}
          >
            <LucideIcon name="upload" size={17} className="" />
            {t("idle.button")}
          </button>

          <button
            className="mt-6 text-sm font-medium text-slate-400 hover:text-[#7aadff] transition-colors"
            onClick={(e) => {
              e.stopPropagation();
              onSample();
            }}
          >
            {t("idle.sample_link")}{" "}
            <span className="underline decoration-slate-200 underline-offset-4">
              {t("idle.sample_action")}
            </span>
          </button>
        </div>
      )}
    </div>
  );
}
