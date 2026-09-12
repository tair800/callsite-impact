import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ErrorPanel, LoadFailureNotice, NothingHere } from "@/components/states";
import type { LoadFailure } from "@/lib/loading";
import { isMissingArtifact, RUN_COMMAND } from "@/lib/loading";

/**
 * A console standing in a checkout where the measurement has never run has exactly one useful
 * thing to say, and it is a command. "No data" is not it. These tests hold the console to naming
 * the absent file and printing `make corpus && make killtest` verbatim, and to keeping that empty
 * state distinct from an outage — a reader who is told the API is unreachable will go and look at
 * the network, which is the wrong place when the truth is that no artifact has ever been produced.
 */

const MISSING_EVALUATION: LoadFailure = {
  kind: "missing_evaluation",
  message: "No evaluation artifact.",
};

const MISSING_DETAIL: LoadFailure = {
  kind: "missing_detail",
  message: "No per-call-site artifact.",
};

describe("the missing-artifact empty state", () => {
  it("prints the exact command that produces the artifact", () => {
    render(<LoadFailureNotice error={MISSING_EVALUATION} />);
    expect(screen.getByText(RUN_COMMAND)).toBeInTheDocument();
    expect(RUN_COMMAND).toBe("make corpus && make killtest");
  });

  it("names the evaluation artifact when that is the file that is absent", () => {
    render(<LoadFailureNotice error={MISSING_EVALUATION} />);
    const panel = screen.getByTestId("artifact-empty-state");
    expect(panel).toHaveTextContent("artifacts/evaluation.json");
    expect(panel).toHaveTextContent(/is not present/i);
  });

  it("names the per-call-site artifact when that is the file that is absent", () => {
    render(<LoadFailureNotice error={MISSING_DETAIL} />);
    expect(screen.getByTestId("artifact-empty-state")).toHaveTextContent("artifacts/findings.json");
  });

  it("offers the API as the alternative, by the server-side variable name", () => {
    render(<LoadFailureNotice error={MISSING_EVALUATION} />);
    const panel = screen.getByTestId("artifact-empty-state");
    expect(panel).toHaveTextContent("IMPACT_API_BASE_URL");
    expect(panel.textContent).not.toContain("NEXT_PUBLIC");
  });

  it("says nothing that could be mistaken for a measurement", () => {
    render(<LoadFailureNotice error={MISSING_EVALUATION} />);
    const panel = screen.getByTestId("artifact-empty-state");
    expect(panel).toHaveTextContent(/never invents one/i);
    expect(screen.queryByTestId("metrics-comparison")).not.toBeInTheDocument();
    expect(screen.queryByTestId("kill-criterion")).not.toBeInTheDocument();
  });

  it("is a status, not an alert — an unrun measurement is not an error", () => {
    render(<LoadFailureNotice error={MISSING_EVALUATION} />);
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});

describe("failures that are not a missing artifact", () => {
  it.each<LoadFailure>([
    { kind: "unreachable", message: "The API is not reachable from the console." },
    { kind: "timeout", message: "The API did not answer within 8 seconds." },
    { kind: "upstream", message: "The API answered 500." },
    { kind: "malformed", message: "artifacts/evaluation.json is not valid JSON." },
    { kind: "not_found", message: "No pair `nope` in findings.json." },
  ])("renders $kind as an error, not as the run-this-command state", (error) => {
    render(<LoadFailureNotice error={error} />);

    expect(isMissingArtifact(error)).toBe(false);
    expect(screen.getByRole("alert")).toHaveTextContent(error.message);
    expect(screen.queryByTestId("artifact-empty-state")).not.toBeInTheDocument();
    expect(screen.queryByText(RUN_COMMAND)).not.toBeInTheDocument();
  });

  it("names the failure class so a maintainer can act on it", () => {
    render(<ErrorPanel error={{ kind: "timeout", message: "It took too long." }} />);
    expect(screen.getByTestId("error-panel")).toHaveTextContent("timeout");
  });
});

describe("a present but empty collection", () => {
  it("is distinct from a missing artifact", () => {
    render(<NothingHere what="spec pairs" />);
    expect(screen.getByRole("status")).toHaveTextContent(
      "The artifact was read and contains no spec pairs.",
    );
    expect(screen.queryByTestId("artifact-empty-state")).not.toBeInTheDocument();
  });
});
