import type { Metadata } from "next";
import {
  Plus_Jakarta_Sans,
  JetBrains_Mono,
  IBM_Plex_Sans_Arabic,
  Tajawal,
  Almarai,
} from "next/font/google";
import "@/styles/globals.css";
import { NextIntlClientProvider } from "next-intl";
import { getMessages } from "next-intl/server";

// إعداد الخط الإنجليزي
const jakartaSans = Plus_Jakarta_Sans({
  subsets: ["latin"],
  variable: "--font-sans",
  display: "swap",
});

const almarai = Almarai({
  subsets: ["arabic"],
  weight: ["300", "400", "700", "800"], // الأوزان المتاحة والمهمة للمراعي
  variable: "--font-almarai",
  display: "swap",
});
export const metadata: Metadata = {
  title: "ProtectMe AI — Understand before you sign",
  description:
    "ProtectMe AI reads your rental, bank, subscription, or service agreement and shows you every risk — in plain language. Then you can ask questions before you commit.",
};

export default async function RootLayout({
  children,
  params: { locale },
}: {
  children: React.ReactNode;
  params: { locale: string };
}) {
  const direction = locale === "ar" ? "rtl" : "ltr";
  const messages = await getMessages({ locale });

  return (
    <html
      lang={locale}
      dir={direction}
      className={`${jakartaSans.variable} ${almarai.variable} font-sans`}
    >
      <body>
        <NextIntlClientProvider messages={messages} locale={locale}>
          {children}
        </NextIntlClientProvider>
      </body>
    </html>
  );
}
