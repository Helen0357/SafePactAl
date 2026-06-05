"use client";

import type { CSSProperties } from "react";
import { LucideIcon } from "@/components/ui/Icon";
import { useTranslations } from "next-intl";

interface DisclaimerProps {
  style?: CSSProperties;
  className?: string;
}

export function Disclaimer({ style, className }: DisclaimerProps) {
  const t = useTranslations("Disclaimer");
  return (
    <div
      className={`flex items-center gap-2 justify-center mt-7 py-4 px-4 border-t text-sm text-[#474747] bg-[#d1d1d128]`}
      style={style}
    >
      <LucideIcon name="info" size={19} />
      <span>{t("text")}</span>
    </div>
  );
}
