import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";
import { Providers } from "./providers";
import { UserMenu } from "@/components/UserMenu";

export const metadata: Metadata = {
  title: "TradingAI",
  description: "AI broker assistant — research & alerts. Not investment advice.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body>
        <Providers>
          <div className="min-h-screen flex flex-col">
            <header className="border-b border-line bg-bg-soft/70 backdrop-blur sticky top-0 z-10">
              <div className="mx-auto max-w-6xl px-4 py-3 flex items-center justify-between">
                <Link href="/" className="font-semibold tracking-tight">
                  TradingAI
                </Link>
                <nav className="flex items-center gap-3 text-sm text-ink-muted overflow-x-auto whitespace-nowrap">
                  <Link href="/" className="hover:text-ink">Dashboard</Link>
                  <Link href="/picks" className="hover:text-ink">Picks</Link>
                  <Link href="/signals" className="hover:text-ink">Signals</Link>
                  <Link href="/gossip" className="hover:text-ink">Gossip</Link>
                  <Link href="/backtest" className="hover:text-ink">Backtest</Link>
                  <Link href="/alerts" className="hover:text-ink">Alerts</Link>
                  <Link href="/thesis" className="hover:text-ink">Theses</Link>
                  <UserMenu />
                </nav>
              </div>
            </header>

            <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
              {children}
            </main>

            <footer className="border-t border-line text-center text-xs text-ink-soft py-4 px-4">
              Not investment advice. TradingAI is a personal research tool. Outputs may be wrong, incomplete, or stale. Do your own research.
            </footer>
          </div>
        </Providers>
      </body>
    </html>
  );
}
