import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VerdictChip, VerdictTriple } from "@/components/chips";

/**
 * The verdict vocabulary is the project's central claim rendered as three words, and the third one
 * is the one that is easy to get wrong. These tests hold UNKNOWN apart from the other two: a
 * refactor that gave it the IMPACTED colour, or dropped the tooltip explaining that the type system
 * cannot decide, would turn an abstention into a soft breakage on every screen at once.
 */
describe("VerdictChip", () => {
  it("renders all three verdicts with their own label and state attribute", () => {
    render(
      <>
        <VerdictChip verdict="impacted" />
        <VerdictChip verdict="unaffected" />
        <VerdictChip verdict="unknown" />
      </>,
    );

    expect(screen.getByText("IMPACTED")).toHaveAttribute("data-verdict", "impacted");
    expect(screen.getByText("UNAFFECTED")).toHaveAttribute("data-verdict", "unaffected");
    expect(screen.getByText("UNKNOWN")).toHaveAttribute("data-verdict", "unknown");
    expect(screen.getAllByTestId("verdict-chip")).toHaveLength(3);
  });

  it("gives UNKNOWN a colour of its own, shared with neither other verdict", () => {
    render(
      <>
        <VerdictChip verdict="impacted" />
        <VerdictChip verdict="unaffected" />
        <VerdictChip verdict="unknown" />
      </>,
    );

    const impacted = screen.getByText("IMPACTED").className;
    const unaffected = screen.getByText("UNAFFECTED").className;
    const unknown = screen.getByText("UNKNOWN").className;

    expect(unknown).toContain("chip-unknown");
    expect(unknown).not.toBe(impacted);
    expect(unknown).not.toBe(unaffected);
    expect(impacted).not.toBe(unaffected);
  });

  it("says on every UNKNOWN that the type system cannot decide, and that it is not a miss", () => {
    render(<VerdictChip verdict="unknown" />);

    const title = screen.getByText("UNKNOWN").getAttribute("title") ?? "";
    expect(title).toMatch(/type system cannot decide/i);
    expect(title).toMatch(/not a miss and not a soft IMPACTED/i);
  });

  it("shows an unrecognised value rather than swallowing it", () => {
    render(<VerdictChip verdict="probably" />);
    expect(screen.getByText("probably")).toBeInTheDocument();
  });
});

describe("VerdictTriple", () => {
  it("puts the compiler, the system and the baseline side by side", () => {
    render(<VerdictTriple truth="impacted" system="unknown" baseline="impacted" />);

    const triple = screen.getByTestId("verdict-triple");
    expect(within(triple).getByTestId("truth-chip")).toHaveTextContent("BREAKS");
    expect(within(triple).getAllByTestId("verdict-chip")).toHaveLength(2);
    expect(within(triple).getByLabelText("System: UNKNOWN")).toBeInTheDocument();
    expect(within(triple).getByLabelText("Baseline: IMPACTED")).toBeInTheDocument();
  });

  it("uses the compiler's own two-valued vocabulary, never a third value", () => {
    render(<VerdictTriple truth="clean" system="unaffected" baseline="impacted" />);
    expect(screen.getByTestId("truth-chip")).toHaveTextContent("CLEAN");
  });
});
