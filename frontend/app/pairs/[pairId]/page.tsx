import Link from "next/link";
import { notFound } from "next/navigation";

import { CallsiteTable } from "@/components/CallsiteTable";
import { ChangeList } from "@/components/ChangeList";
import { PairProvenancePanel } from "@/components/PairProvenancePanel";
import { LoadFailureNotice } from "@/components/states";
import { count } from "@/lib/format";
import { loadPairDetail, loadPairIndex, loadProvenance } from "@/lib/source";
import type { PairProvenance } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * One spec pair, top to bottom: where it came from, what changed, and what happened to each call
 * site when the compiler was pointed at it.
 *
 * Two loads, and the second one is allowed to fail on its own. `findings.json` is what this screen
 * is about; `evaluation.json` contributes only the checksums, the dates and the licence. A reader
 * with the detail artifact and no evaluation artifact should still get the story, with the missing
 * fields named rather than blank.
 */
export default async function PairPage({
  params,
}: {
  params: Promise<{ pairId: string }>;
}): Promise<React.ReactElement> {
  const { pairId } = await params;
  const [detail, provenance, index] = await Promise.all([
    loadPairDetail(pairId),
    loadProvenance(),
    loadPairIndex(),
  ]);

  if (!detail.ok) {
    // A pair id that is not in the artifact is a URL that does not exist, and answering it with a
    // 200 and an explanation would tell a crawler — and a reader's browser history — otherwise.
    // Every other failure keeps its explanation, because those are about the console, not the URL.
    if (detail.error.kind === "not_found") {
      notFound();
    }
    return (
      <div className="space-y-4">
        <Breadcrumb pairId={pairId} />
        <LoadFailureNotice error={detail.error} />
      </div>
    );
  }

  const pair = detail.data;
  const pairProvenance: PairProvenance | null = provenance.ok
    ? (provenance.data.pairs.find((entry) => entry.pair_id === pair.pair_id) ?? null)
    : null;
  const sampling = index.ok ? index.data.sampling : "";

  return (
    <div className="space-y-4">
      <Breadcrumb pairId={pair.pair_id} />

      <div className="px-1">
        <h1 className="text-[17px] font-bold tracking-tight text-[var(--color-text)]">
          {pair.vendor} · {pair.service}
        </h1>
        <p className="mono mt-1 text-[12px] text-[var(--color-muted)]">
          {pair.before_revision} → {pair.after_revision}
        </p>
      </div>

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Figure label="Changes reported" value={count(pair.changes_total)} />
        <Figure
          label="Call sites admitted"
          value={count(pair.callsites_admitted)}
          hint="Typechecked clean against the before revision before admission."
        />
        <Figure
          label="Compiler breakages"
          value={count(pair.callsites_broken)}
          hint="Call sites tsc errored on against the after revision."
        />
        <Figure
          label="Clean call sites omitted"
          value={count(pair.clean_callsites_omitted)}
          hint="Left out of this display sample by the per-pair cap. Every breakage is included."
        />
      </div>

      <PairProvenancePanel pair={pair} provenance={pairProvenance} />

      <ChangeList changes={pair.changes_shown} total={pair.changes_total} />

      <CallsiteTable
        callsites={pair.callsites}
        cleanOmitted={pair.clean_callsites_omitted}
        sampling={sampling}
      />
    </div>
  );
}

function Breadcrumb({ pairId }: { pairId: string }): React.ReactElement {
  return (
    <p className="px-1 text-[11.5px] text-[var(--color-dim)]">
      <Link href="/pairs" className="text-[var(--color-accent)] underline underline-offset-2">
        spec pairs
      </Link>{" "}
      / <code className="mono">{pairId}</code>
    </p>
  );
}

function Figure({
  label,
  value,
  hint,
}: {
  label: string;
  value: string;
  hint?: string;
}): React.ReactElement {
  return (
    <div className="panel px-4 py-3" title={hint}>
      <div className="kicker">{label}</div>
      <div className="mono mt-0.5 text-[16px] font-bold text-[var(--color-text)]">{value}</div>
    </div>
  );
}
