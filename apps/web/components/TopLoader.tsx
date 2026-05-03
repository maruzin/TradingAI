"use client";
import { useEffect, useState } from "react";
import { usePathname, useSearchParams } from "next/navigation";

/**
 * Vercel/Linear-style top progress bar that animates on every route change.
 * Sits at the top of the viewport, ~2px tall, accent gradient.
 */
export function TopLoader() {
  const pathname = usePathname();
  const sp = useSearchParams();
  const [visible, setVisible] = useState(false);
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    setVisible(true);
    setProgress(15);
    const t1 = setTimeout(() => setProgress(45), 120);
    const t2 = setTimeout(() => setProgress(80), 380);
    const t3 = setTimeout(() => {
      setProgress(100);
      setTimeout(() => { setVisible(false); setProgress(0); }, 220);
    }, 700);
    return () => { clearTimeout(t1); clearTimeout(t2); clearTimeout(t3); };
  }, [pathname, sp]);

  if (!visible) return null;
  return (
    <div className="fixed top-0 left-0 right-0 z-[100] h-[2px] pointer-events-none">
      <div
        className="h-full bg-gradient-to-r from-accent via-bull to-accent transition-all duration-300 ease-out shadow-[0_0_8px_var(--tw-shadow-color)] shadow-accent"
        style={{ width: `${progress}%` }}
      />
    </div>
  );
}
