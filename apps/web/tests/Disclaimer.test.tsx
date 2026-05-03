import { render, screen } from "@testing-library/react";
import { describe, it, expect } from "vitest";
import { Disclaimer } from "@/components/Disclaimer";

describe("<Disclaimer />", () => {
  it("renders the not-investment-advice text", () => {
    render(<Disclaimer />);
    expect(
      screen.getByText(/not investment advice/i),
    ).toBeInTheDocument();
  });
});
