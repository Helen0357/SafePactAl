"use client";
import { Button } from "@/components/ui/Button";
import { LucideIcon } from "@/components/ui/Icon";
import { Link, usePathname, useRouter } from "@/i18n/routing";
import { useLocale, useTranslations } from "next-intl";
import Image from "next/image";

interface NavProps {
  onHome?: () => void;
  showNewContract?: boolean;
}

export function Nav({ onHome, showNewContract }: NavProps) {
  const locale = useLocale();
  const t = useTranslations("Nav");

  const router = useRouter();
  const pathname = usePathname();
  const toggleLanguage = (newLocale: "en" | "ar") => {
    if (newLocale === locale) return;
    router.replace(pathname, { locale: newLocale });
  };
  return (
    <nav className="nav px-14 border-b border-gray-200 z-40 bg-white">
      <div
        className="wrap"
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          width: "100%",
        }}
      >
        <button
          className="group flex items-center gap-2 hover:opacity-90 transition-all duration-300"
          onClick={onHome}
          aria-label={t("go_home")}
        >
          {/* <div className="relative w-8 h-8 flex items-center justify-center rounded-xs bg-gradient-to-br from-[#67a1ff] via-[#7aadff] to-cyan-500 shadow-lg shadow-blue-200/50 group-hover:scale-105 transition-transform">
            <LucideIcon name="shield-check" size={20} color="#fff" />
            <div className="absolute inset-0 bg-white/10 rounded-[12px] pointer-events-none" />
          </div> */}
          <Image src="/logo.png" alt="logo" width={180} height={60} />
        </button>

        <div className="nav-links">
          <div className="relative flex items-center p-1 mx-3 bg-slate-100 rounded-full border border-slate-200 h-9 w-[110px]">
            <div
              className={`absolute h-7 w-[52px] bg-white rounded-full shadow-sm transition-all duration-300 ease-in-out border border-slate-100
              ${locale === "ar" ? "translate-x-0" : "translate-x-[48px]"}`}
            />

            <button
              onClick={() => toggleLanguage("ar")}
              className={`relative z-10 flex-1 text-[11px] font-medium transition-colors duration-300 ${locale === "ar" ? "text-[#67a1ff]" : "text-slate-400"}`}
            >
              {t("ar")}
            </button>

            <button
              onClick={() => toggleLanguage("en")}
              className={`relative z-10 flex-1 text-[11px] font-medium transition-colors duration-300 ${locale === "en" ? "text-[#67a1ff]" : "text-slate-400"}`}
            >
              {t("en")}
            </button>
          </div>
          <Link
            href="/#how_it_work"
            className="bg-[#7aadff] text-white px-4 py-2 rounded-xs text-sm"
          >
            {t("how_it_works")}
          </Link>

          {showNewContract && (
            <Button
              variant="secondary"
              onDark
              size="sm"
              icon="plus"
              onClick={onHome}
              className="!text-[#67a1ff] !border-[#67a1ff]"
            >
              {t("new_contract")}
            </Button>
          )}
        </div>
      </div>
    </nav>
  );
}
