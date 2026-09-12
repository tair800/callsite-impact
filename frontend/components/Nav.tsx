"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const LINKS: { href: string; label: string }[] = [
  { href: "/", label: "Result" },
  { href: "/pairs", label: "Spec pairs" },
  { href: "/provenance", label: "Provenance" },
];

function isActive(pathname: string, href: string): boolean {
  return href === "/" ? pathname === "/" : pathname.startsWith(href);
}

export function Nav(): React.ReactElement {
  const pathname = usePathname();
  return (
    <header className="border-b border-[var(--color-line)] bg-[var(--color-panel)]">
      <div className="mx-auto flex max-w-[1180px] items-center gap-6 px-5 py-2.5">
        <Link href="/" className="mono text-[12.5px] font-bold tracking-tight text-[var(--color-text)]">
          callsite-impact
        </Link>
        <nav className="flex items-center gap-1" aria-label="Console sections">
          {LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="nav-link"
              data-active={isActive(pathname, link.href)}
            >
              {link.label}
            </Link>
          ))}
        </nav>
        <span className="ml-auto hidden text-[11px] text-[var(--color-dim)] sm:block">
          ground truth: the TypeScript compiler
        </span>
      </div>
    </header>
  );
}
