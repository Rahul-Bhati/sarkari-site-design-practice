import type { Metadata, Viewport } from "next";
import { Toaster } from "sonner";
import { Footer } from "@/components/layout/Footer";
import { Navbar } from "@/components/layout/Navbar";
import "./globals.css";

const SITE_URL = process.env.NEXT_PUBLIC_SITE_URL ?? "https://sarkarisaar.com";

export const metadata: Metadata = {
  metadataBase: new URL(SITE_URL),
  title: {
    default: "SarkariSaar — Government updates in plain language",
    template: "%s | SarkariSaar",
  },
  description:
    "Sarkari yojana, naukri, tenders and rule changes from across India — summarised in simple English and Hindi, with deadlines you can actually see.",
  keywords: [
    "sarkari yojana",
    "government tender",
    "sarkari naukri",
    "ssc notification",
    "government schemes India",
  ],
  openGraph: {
    type: "website",
    siteName: "SarkariSaar",
    locale: "en_IN",
  },
  twitter: { card: "summary_large_image" },
  robots: { index: true, follow: true },
};

export const viewport: Viewport = {
  themeColor: "#0A0A0F",
  width: "device-width",
  initialScale: 1,
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className="flex min-h-dvh flex-col">
        <Navbar />
        <main className="grow">{children}</main>
        <Footer />
        <Toaster theme="dark" position="top-center" richColors />
      </body>
    </html>
  );
}
