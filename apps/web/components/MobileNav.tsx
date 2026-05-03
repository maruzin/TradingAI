"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import { LayoutGrid, Sparkles, Activity, Newspaper, Wallet, BarChart3, Bell, FileText } from "lucide-react";

const ITEMS = [
  { href: "/",         label: "Home",     Icon: LayoutGrid },
  { href: "/picks",    label: "Picks",    Icon: Sparkles },
  { href: "/signals",  label: "Signals",  Icon: Activity },
  { href: "/wallets",  label: "Wallets",  Icon: Wallet },
  { href: "/gossip",   label: "Gossip",   Icon: Newspaper },
];

/**
 * Bottom-tab navigation, mobile only. Hidden on ≥sm screens (header nav takes
 * over). Touch targets are 44px+ per Apple HIG / Material guidelines.
 */
export function MobileNav() {
  const pathname = usePathname();
  return (
    <nav className="sm:hidden fixed bottom-0 left-0 right-0 z-40 border-t border-line bg-bg-soft/95 backdrop-blur supports-[backdrop-filter]:bg-bg-soft/80">
      <ul className="grid grid-cols-5">
        {ITEMS.map(({ href, label, Icon }) => {
          const active = pathname === href || (href !== "/" && pathname.startsWith(href));
          return (
            <li key={href}>
              <Link
                href={href}
                className={clsx(
                  "flex flex-col items-center justify-center gap-0.5 py-2.5 text-[10px] transition-colors",
                  active ? "text-accent" : "text-ink-soft hover:text-ink",
                )}
              >
                <Icon className="size-5" strokeWidth={active ? 2.5 : 1.75} />
                <span>{label}</span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
