"use client";
import { createContext, useContext, useId, useState, type ReactNode, type KeyboardEvent } from "react";
import clsx from "clsx";

/**
 * Tabs — minimal accessible tab implementation.
 *
 * Usage:
 *   <Tabs defaultValue="overview">
 *     <Tabs.List>
 *       <Tabs.Trigger value="overview">Overview</Tabs.Trigger>
 *       <Tabs.Trigger value="signals">Signals</Tabs.Trigger>
 *     </Tabs.List>
 *     <Tabs.Panel value="overview">…</Tabs.Panel>
 *     <Tabs.Panel value="signals">…</Tabs.Panel>
 *   </Tabs>
 *
 * Implements role=tablist/tab/tabpanel + aria-selected + arrow-key
 * navigation. No external dep — radix-ui isn't pulled in for one component.
 */

interface TabsContext {
  value: string;
  setValue: (v: string) => void;
  baseId: string;
}

const Ctx = createContext<TabsContext | null>(null);
function useTabs() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("Tabs.* must be used inside <Tabs>");
  return ctx;
}

interface TabsRootProps {
  defaultValue: string;
  value?: string;
  onValueChange?: (v: string) => void;
  children: ReactNode;
  className?: string;
}

function Root({ defaultValue, value: controlled, onValueChange, children, className }: TabsRootProps) {
  const [internal, setInternal] = useState(defaultValue);
  const baseId = useId();
  const value = controlled ?? internal;
  const setValue = (v: string) => {
    if (controlled === undefined) setInternal(v);
    onValueChange?.(v);
  };
  return (
    <Ctx.Provider value={{ value, setValue, baseId }}>
      <div className={clsx("flex flex-col", className)}>{children}</div>
    </Ctx.Provider>
  );
}

function List({ children, className }: { children: ReactNode; className?: string }) {
  const onArrowKey = (e: KeyboardEvent<HTMLDivElement>) => {
    if (e.key !== "ArrowLeft" && e.key !== "ArrowRight") return;
    const triggers = Array.from(
      e.currentTarget.querySelectorAll<HTMLButtonElement>("[role='tab']:not([disabled])"),
    );
    const i = triggers.findIndex((t) => t === document.activeElement);
    if (i < 0) return;
    const next = e.key === "ArrowRight" ? (i + 1) % triggers.length : (i - 1 + triggers.length) % triggers.length;
    triggers[next].focus();
    triggers[next].click();
    e.preventDefault();
  };
  return (
    <div
      role="tablist"
      onKeyDown={onArrowKey}
      className={clsx(
        "inline-flex items-center gap-0.5 rounded-md border border-line bg-bg-subtle p-0.5",
        className,
      )}
    >
      {children}
    </div>
  );
}

interface TriggerProps {
  value: string;
  children: ReactNode;
  className?: string;
  disabled?: boolean;
}

function Trigger({ value, children, className, disabled }: TriggerProps) {
  const { value: active, setValue, baseId } = useTabs();
  const selected = active === value;
  return (
    <button
      type="button"
      role="tab"
      id={`${baseId}-tab-${value}`}
      aria-controls={`${baseId}-panel-${value}`}
      aria-selected={selected}
      tabIndex={selected ? 0 : -1}
      disabled={disabled}
      onClick={() => setValue(value)}
      className={clsx(
        "h-7 px-2.5 rounded text-caption font-medium",
        "transition-colors duration-fast ease-standard",
        "focus-visible:outline-none focus-visible:shadow-focus",
        "disabled:opacity-50 disabled:cursor-not-allowed",
        selected
          ? "bg-bg-elevated text-ink shadow-subtle"
          : "text-ink-muted hover:text-ink hover:bg-bg-soft",
        className,
      )}
    >
      {children}
    </button>
  );
}

interface PanelProps {
  value: string;
  children: ReactNode;
  className?: string;
  /** Keep the DOM mounted when inactive. Default true so Tab inputs preserve state. */
  forceMount?: boolean;
}

function Panel({ value, children, className, forceMount = true }: PanelProps) {
  const { value: active, baseId } = useTabs();
  const selected = active === value;
  if (!selected && !forceMount) return null;
  return (
    <div
      role="tabpanel"
      id={`${baseId}-panel-${value}`}
      aria-labelledby={`${baseId}-tab-${value}`}
      hidden={!selected}
      className={clsx(selected && "animate-fade-in", className)}
    >
      {selected && children}
    </div>
  );
}

type TabsComponent = typeof Root & {
  List: typeof List;
  Trigger: typeof Trigger;
  Panel: typeof Panel;
};

const Tabs = Root as TabsComponent;
Tabs.List = List;
Tabs.Trigger = Trigger;
Tabs.Panel = Panel;

export { Tabs };
