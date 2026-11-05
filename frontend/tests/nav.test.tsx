import { render, screen, within } from "@testing-library/react";
import { usePathname } from "next/navigation";
import { describe, expect, it, vi } from "vitest";

import { Nav } from "@/components/Nav";

vi.mock("next/navigation", () => ({ usePathname: vi.fn() }));

/**
 * The nav shows which section a reader is in by styling the active link, and styling is invisible
 * to a screen reader. These tests hold it to exposing the same fact as `aria-current="page"`, on the
 * active link and on no other, so a reader who cannot see the highlight is still told where they are.
 */

function renderAt(pathname: string): void {
  vi.mocked(usePathname).mockReturnValue(pathname);
  render(<Nav />);
}

function navLink(name: string): HTMLElement {
  const nav = screen.getByRole("navigation", { name: "Console sections" });
  return within(nav).getByRole("link", { name });
}

describe("Nav", () => {
  it("marks the section the reader is on as the current page, and only that one", () => {
    renderAt("/");
    expect(navLink("Result")).toHaveAttribute("aria-current", "page");
    expect(navLink("Spec pairs")).not.toHaveAttribute("aria-current");
    expect(navLink("Provenance")).not.toHaveAttribute("aria-current");
  });

  it("marks a section's own page as the current page", () => {
    renderAt("/pairs");
    expect(navLink("Spec pairs")).toHaveAttribute("aria-current", "page");
  });

  it("marks a section as current, not as the current page, on the routes nested under it", () => {
    renderAt("/pairs/adyen-checkout-v71-to-v72");
    expect(navLink("Spec pairs")).toHaveAttribute("aria-current", "true");
    expect(navLink("Result")).not.toHaveAttribute("aria-current");
    expect(navLink("Provenance")).not.toHaveAttribute("aria-current");
  });

  it("does not count a path that only shares a section's prefix as inside it", () => {
    renderAt("/pairsx");
    expect(navLink("Spec pairs")).toHaveAttribute("data-active", "false");
    expect(navLink("Spec pairs")).not.toHaveAttribute("aria-current");
  });
});
