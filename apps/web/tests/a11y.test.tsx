import { render } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import axe, { run } from "axe-core";
import { Disclaimer } from "@/components/Disclaimer";

/**
 * Smoke a11y test. Asserts no WCAG 2.1 AA violations on a known component.
 * Lightweight — runs in jsdom, doesn't catch every issue (no real layout
 * means contrast on actual rendered pixels isn't reliable here), but
 * catches missing labels, role mistakes, and structural problems.
 */
describe("a11y", () => {
  it("Disclaimer has no axe violations", async () => {
    const { container } = render(<Disclaimer />);
    const results = await new Promise<{ violations: any[] }>((resolve, reject) => {
      run(container, { runOnly: ["wcag2a", "wcag2aa"] }, (err, r) => {
        if (err) reject(err);
        else resolve(r);
      });
    });
    if (results.violations.length > 0) {
      // eslint-disable-next-line no-console
      console.error("axe violations:", JSON.stringify(results.violations, null, 2));
    }
    expect(results.violations).toEqual([]);
  });
});
