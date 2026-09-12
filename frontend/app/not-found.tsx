import Link from "next/link";

export default function NotFound(): React.ReactElement {
  return (
    <div className="panel px-5 py-6">
      <p className="kicker mb-2">Not here</p>
      <p className="text-[13px] text-[var(--color-text)]">
        This console has three screens: the result, the spec pairs, and the provenance of every
        specification it read.
      </p>
      <p className="mt-3 text-[12.5px]">
        <Link href="/" className="text-[var(--color-accent)] underline underline-offset-2">
          Back to the result
        </Link>
      </p>
    </div>
  );
}
