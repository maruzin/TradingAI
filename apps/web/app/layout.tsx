import "./globals.css";
import type { Metadata, Viewport } from "next";
import { Inter, JetBrains_Mono } from "next/font/google";
import Link from "next/link";
import { Suspense } from "react";
import { Providers } from "./providers";
import { UserMenu } from "@/components/UserMenu";
import { MobileNav } from "@/components/MobileNav";
import { TopLoader } from "@/components/TopLoader";
import { HealthIndicator } from "@/components/HealthIndicator";
import { RegimeBadge } from "@/components/RegimeBadge";
import { ThemeApplier } from "@/components/ThemeApplier";
import { KeyboardShortcuts } from "@/components/KeyboardShortcuts";
import { ServiceWorkerRegister } from "@/components/ServiceWorkerRegister";

const inter = Inter({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-sans",
});
const mono = JetBrains_Mono({
  subsets: ["latin"],
  display: "swap",
  variable: "--font-mono",
});

export const metadata: Metadata = {
  title: "TradingAI",
  description: "AI broker assistant — research & alerts. Not investment advice.",
  manifest: "/manifest.json",
  appleWebApp: {
    capable: true,
    statusBarStyle: "black-translucent",
    title: "TradingAI",
  },
};

export const viewport: Viewport = {
  themeColor: "#0b0d10",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  userScalable: true,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`dark ${inter.variable} ${mono.variable}`}>
      <body className="font-sans">
        <Providers>
          <ThemeApplier />
          <KeyboardShortcuts />
          <ServiceWorkerRegister />
          <Suspense fallback={null}>
            <TopLoader />
          </Suspense>
          <div className="min-h-screen flex flex-col safe-area-y">
            <header className="border-b border-line bg-bg-soft/80 backdrop-blur sticky top-0 z-30 supports-[backdrop-filter]:bg-bg-soft/60">
              <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between gap-3">
                <Link href="/" className="font-semibold tracking-tight flex items-center gap-2 shrink-0">
                  <span className="size-2 rounded-full bg-gradient-to-br from-accent to-bull shadow-[0_0_10px] shadow-accent" />
                  TradingAI
                </Link>
                {/* Desktop nav (≥sm); mobile uses bottom MobileNav instead */}
                <nav className="hidden sm:flex items-center gap-3 text-sm text-ink-muted overflow-x-auto whitespace-nowrap">
                  <Link href="/" className="hover:text-ink transition-colors">Dashboard</Link>
                  <Link href="/picks" className="hover:text-ink transition-colors">Picks</Link>
                  <Link href="/signals" className="hover:text-ink transition-colors">Signals</Link>
                  <Link href="/gossip" className="hover:text-ink transition-colors">Gossip</Link>
                  <Link href="/wallets" className="hover:text-ink transition-colors">Wallets</Link>
                  <Link href="/backtest" className="hover:text-ink transition-colors">Backtest</Link>
                  <Link href="/ev" className="hover:text-ink transition-colors">EV</Link>
                  <Link href="/compare" className="hover:text-ink transition-colors">Compare</Link>
                  <Link href="/alerts" className="hover:text-ink transition-colors">Alerts</Link>
                  <Link href="/thesis" className="hover:text-ink transition-colors">Theses</Link>
                </nav>
                <div className="flex items-center gap-3">
                  <RegimeBadge />
                  <HealthIndicator />
                  <UserMenu />
                </div>
              </div>
            </header>

            <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6 pb-24 sm:pb-6">
              {children}
            </main>

            <footer className="border-t border-line text-center text-[11px] sm:text-xs text-ink-soft py-3 px-4 mb-16 sm:mb-0">
              Not investment advice. TradingAI is a personal research tool. Outputs may be wrong, incomplete, or stale. Do your own research.
            </footer>

            <MobileNav />
          </div>
        </Providers>
      </body>
    </html>
  );
}
