import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { KillCriterionPanel } from "@/components/KillCriterionPanel";
import { FAILED_SUMMARY, SUMMARY } from "@/tests/fixtures";

/**
 * ADR-001: if the corpus cannot reach 60 breakages across three vendors honestly, the claim is not
 * proven and the repository says so on its front page. A failure that renders as a caveat is a
 * failure being softened, so this test asserts the word, the shortfall and the sentence.
 */
describe("KillCriterionPanel", () => {
  it("reports a pass with the observed counts against the predeclared thresholds", () => {
    render(<KillCriterionPanel criterion={SUMMARY.kill_criterion} />);

    const panel = screen.getByTestId("kill-criterion");
    expect(panel).toHaveAttribute("data-passed", "true");
    expect(panel).toHaveTextContent("PASSED");
    expect(panel).toHaveTextContent("71 compiler-verified call-site breakages across 3 vendors");
    expect(panel).toHaveTextContent("threshold of 60 across 3");
  });

  it("reports a failure plainly, and does not soften it", () => {
    render(<KillCriterionPanel criterion={FAILED_SUMMARY.kill_criterion} />);

    const panel = screen.getByTestId("kill-criterion");
    expect(panel).toHaveAttribute("data-passed", "false");
    expect(panel).toHaveTextContent("FAILED");
    expect(panel).toHaveTextContent("41 compiler-verified call-site breakages across 2 vendors");
    expect(panel).toHaveTextContent(/not proven/i);
    expect(panel).toHaveTextContent(/The criterion is not lowered/i);
  });

  it("marks each condition separately, so a partial result cannot read as a pass", () => {
    render(<KillCriterionPanel criterion={FAILED_SUMMARY.kill_criterion} />);
    const panel = screen.getByTestId("kill-criterion");

    // 41 breakages is short of 60 and 2 vendors is short of 3: both conditions unmet.
    expect(panel).toHaveTextContent("breakages 41 / 60");
    expect(panel).toHaveTextContent("vendors 2 / 3");
    expect(screen.getAllByText("NOT MET")).toHaveLength(2);
  });

  it("takes `passed` from the artifact rather than deciding it in the browser", () => {
    // The Python model derives `passed`; a console that re-derived it would be a second place the
    // criterion could be relaxed. Here the field disagrees with the counts on purpose.
    render(
      <KillCriterionPanel
        criterion={{
          threshold: 60,
          vendors_required: 3,
          observed_breakages: 12,
          observed_vendors: 1,
          passed: true,
        }}
      />,
    );
    expect(screen.getByTestId("kill-criterion")).toHaveTextContent("PASSED");
  });
});
