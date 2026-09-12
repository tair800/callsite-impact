import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { MetricsComparison } from "@/components/MetricsComparison";
import { BASELINE_ERR, BASELINE_TOUCHES, SYSTEM_REPORT } from "@/tests/fixtures";

/**
 * ADR-001 computes both readings for every scope and says nothing offers a way to publish one
 * without the other. These tests pin that to the UI: the strict reading is what a reader lands on,
 * the abstaining reading is one click away, the sentence explaining the difference is on screen in
 * both, and the abstaining view discloses how many call sites it dropped to get its better numbers.
 */

function renderComparison(): void {
  render(
    <MetricsComparison
      system={SYSTEM_REPORT}
      baselineTouches={BASELINE_TOUCHES}
      baselineErr={BASELINE_ERR}
    />,
  );
}

function headlineFor(rowKey: string): string {
  const row = screen.getByTestId(`metrics-row-${rowKey}`);
  const cells = within(row).getAllByRole("cell");
  return cells[0]?.textContent ?? "";
}

describe("MetricsComparison", () => {
  it("opens on the strict view", () => {
    renderComparison();
    expect(screen.getByRole("button", { name: "strict" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByRole("button", { name: "abstaining" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("shows the system's strict false-negative rate, counting abstentions as misses", () => {
    renderComparison();
    // 7 missed breakages of 71 compiler-labelled ones, 5 of them abstentions.
    expect(headlineFor("system")).toBe("9.9%");
  });

  it("switches to the abstaining view and the headline changes with it", () => {
    renderComparison();
    fireEvent.click(screen.getByRole("button", { name: "abstaining" }));

    // The same system, with the 41 abstentions removed from the matrix: 2 misses of 66.
    expect(headlineFor("system")).toBe("3.0%");
    expect(screen.getByRole("button", { name: "abstaining" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
  });

  it("keeps both baselines on the table in both views", () => {
    renderComparison();
    expect(headlineFor("baseline-touches")).toBe("0.0%");
    expect(headlineFor("baseline-err")).toBe("4.2%");

    fireEvent.click(screen.getByRole("button", { name: "abstaining" }));

    // Neither baseline ever abstains, so neither moves. Both must still be rendered.
    expect(headlineFor("baseline-touches")).toBe("0.0%");
    expect(headlineFor("baseline-err")).toBe("4.2%");
  });

  it("explains what each view does with an UNKNOWN, in both views", () => {
    renderComparison();
    expect(screen.getByTestId("view-note")).toHaveTextContent(/counts an UNKNOWN as a miss/i);

    fireEvent.click(screen.getByRole("button", { name: "abstaining" }));
    expect(screen.getByTestId("view-note")).toHaveTextContent(
      /removes every call site the system abstained on/i,
    );
  });

  it("discloses the excluded call sites only in the view that excluded them", () => {
    renderComparison();
    expect(screen.queryByRole("columnheader", { name: "Excluded" })).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "abstaining" }));
    expect(screen.getByRole("columnheader", { name: "Excluded" })).toBeInTheDocument();

    const row = screen.getByTestId("metrics-row-system");
    expect(within(row).getAllByRole("cell").at(-2)?.textContent).toBe("41");
  });

  it("shows the naive baseline over-reporting: perfect recall, poor precision", () => {
    renderComparison();
    const row = screen.getByTestId("metrics-row-baseline-touches");
    const cells = within(row).getAllByRole("cell");

    expect(cells[1]?.textContent).toBe("46.7%"); // false-positive rate
    expect(cells[2]?.textContent).toBe("32.4%"); // precision
    expect(cells[3]?.textContent).toBe("100.0%"); // recall
  });

  it("scopes to one vendor without changing which predictors are compared", () => {
    renderComparison();
    fireEvent.click(screen.getByRole("button", { name: "adyen" }));

    // 4 missed breakages of 31, for adyen alone.
    expect(headlineFor("system")).toBe("12.9%");
    expect(screen.getByTestId("metrics-row-baseline-touches")).toBeInTheDocument();
    expect(screen.getByTestId("metrics-row-baseline-err")).toBeInTheDocument();
  });
});
