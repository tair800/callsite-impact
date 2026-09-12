import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CallsiteTable } from "@/components/CallsiteTable";
import { disagreesWithCompiler } from "@/lib/verdicts";
import { CALLSITES, SAMPLING } from "@/tests/fixtures";

/**
 * The rows where the compiler and a predictor disagree are the reason this console exists, and the
 * filter is how a reader reaches them. The predicate is asserted directly as well as through the
 * UI, because it has to keep mirroring `scorer._view(abstaining=False)`: if an UNKNOWN on a *clean*
 * call site ever started counting as a disagreement, the filter would select a different set of
 * rows from the one the published false-positive count was computed over.
 */

function renderTable(): void {
  render(<CallsiteTable callsites={CALLSITES} cleanOmitted={108} sampling={SAMPLING} />);
}

function visibleIds(): string[] {
  return screen
    .getAllByTestId("callsite-row")
    .map((row) => row.getAttribute("data-callsite-id") ?? "");
}

describe("disagreesWithCompiler", () => {
  it("counts a missed breakage as a disagreement, abstentions included", () => {
    expect(disagreesWithCompiler("impacted", "unaffected")).toBe(true);
    expect(disagreesWithCompiler("impacted", "unknown")).toBe(true);
    expect(disagreesWithCompiler("impacted", "impacted")).toBe(false);
  });

  it("counts only a reported IMPACTED on a clean call site, never an abstention", () => {
    expect(disagreesWithCompiler("clean", "impacted")).toBe(true);
    expect(disagreesWithCompiler("clean", "unknown")).toBe(false);
    expect(disagreesWithCompiler("clean", "unaffected")).toBe(false);
  });
});

describe("CallsiteTable filters", () => {
  it("shows every sampled call site by default", () => {
    renderTable();
    expect(visibleIds()).toHaveLength(CALLSITES.length);
    expect(screen.getByTestId("row-count")).toHaveTextContent("Showing 6 of 6");
  });

  it("filters to the rows where the system disagrees with the compiler", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "system ≠ compiler" }));

    expect(visibleIds()).toEqual([
      "cs_system_abstains_on_break",
      "cs_both_miss",
      "cs_system_false_positive",
    ]);
    expect(screen.getByTestId("row-count")).toHaveTextContent("Showing 3 of 6");
  });

  it("filters to the rows where the baseline disagrees, which is a different set", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "baseline ≠ compiler" }));

    expect(visibleIds()).toEqual([
      "cs_baseline_overreports",
      "cs_both_miss",
      "cs_system_false_positive",
    ]);
  });

  it("keeps an abstention on a clean call site out of the disagreement set", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "system ≠ compiler" }));
    expect(visibleIds()).not.toContain("cs_abstention_on_clean");

    fireEvent.click(screen.getByRole("button", { name: "system abstained" }));
    expect(visibleIds()).toEqual(["cs_system_abstains_on_break", "cs_abstention_on_clean"]);
  });

  it("filters to the compiler's own breakages", () => {
    renderTable();
    fireEvent.click(screen.getByRole("button", { name: "compiler breakages" }));
    expect(visibleIds()).toEqual([
      "cs_agree_impacted",
      "cs_system_abstains_on_break",
      "cs_both_miss",
    ]);
  });

  it("marks the active filter as pressed and returns to all rows", () => {
    renderTable();
    const breakages = screen.getByRole("button", { name: "compiler breakages" });
    fireEvent.click(breakages);
    expect(breakages).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByRole("button", { name: "all" }));
    expect(breakages).toHaveAttribute("aria-pressed", "false");
    expect(visibleIds()).toHaveLength(6);
  });

  it("says the sample is a sample, and how many clean call sites it left out", () => {
    renderTable();
    expect(screen.getByTestId("clean-omitted")).toHaveTextContent(
      "108 clean call sites from this pair are not shown.",
    );
    expect(screen.getByText(/Every call site the compiler broke is included/)).toBeInTheDocument();
  });

  it("expands a row to its source, its diagnostics and the change each finding is anchored to", () => {
    renderTable();
    const row = screen
      .getAllByTestId("callsite-row")
      .find((element) => element.getAttribute("data-callsite-id") === "cs_agree_impacted");
    expect(row).toBeDefined();

    fireEvent.click(within(row!).getByRole("button", { name: "evidence" }));

    const detail = screen.getByTestId("callsite-detail");
    expect(detail).toHaveTextContent("shopperInteraction");
    expect(detail).toHaveTextContent("TS2353");
    expect(detail).toHaveTextContent("request-property-removed");
    expect(detail).toHaveTextContent("sets_removed_request_property");
  });

  it("explains an empty filter result as a filter result, not as missing data", () => {
    render(
      <CallsiteTable
        callsites={CALLSITES.filter((row) => row.truth === "clean" && row.system === "unaffected")}
        cleanOmitted={0}
        sampling={SAMPLING}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "compiler breakages" }));

    expect(screen.getByRole("status")).toHaveTextContent(
      /this is a filter result, not missing data/i,
    );
    expect(screen.queryByTestId("artifact-empty-state")).not.toBeInTheDocument();
  });
});
