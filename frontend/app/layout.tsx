import type { Metadata } from "next";

import { Nav } from "@/components/Nav";

import "./globals.css";

export const metadata: Metadata = {
  title: "callsite-impact",
  description:
    "Which client call sites an OpenAPI revision actually breaks, graded by the TypeScript compiler.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>): React.ReactElement {
  return (
    <html lang="en">
      <body>
        <Nav />
        <main className="mx-auto max-w-[1180px] px-5 py-6">{children}</main>
        <footer className="mx-auto max-w-[1180px] px-5 pb-10 pt-4 text-[11px] text-[var(--color-dim)]">
          Every figure on this console is read from a committed artifact produced by{" "}
          <code className="mono">make killtest</code>. Nothing is computed in the browser.
        </footer>
      </body>
    </html>
  );
}
