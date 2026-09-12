/**
 * What compiler verification proves, and what it does not.
 *
 * Four sentences, every clause of which is taken from `DECISIONS.md` ADR-001 and `CLAUDE.md` rule
 * 5. Nothing here is a claim this component invented, and it is static text rather than anything
 * derived from the artifact — a sentence about what a measurement *means* should not change when
 * the measurement does.
 */
export function WhatThisProves(): React.ReactElement {
  return (
    <section className="panel" data-testid="what-this-proves">
      <div className="panel-head rounded-t-[5px] px-4 py-2">
        <h2 className="kicker">What this proves, and what it does not</h2>
      </div>
      <div className="px-4 py-3">
        <p className="max-w-[78ch] text-[13px] leading-relaxed text-[var(--color-text)]">
          The answer key is the TypeScript compiler, not a human and not a model: call sites are
          generated from revision A and typecheck clean against it by construction, then recompiled
          unchanged against revision B, where <code className="mono">tsc</code> emits the labels.
          A label proves a <em>type-level</em> incompatibility at a <em>generated</em> call site
          against a <em>generated</em> client — it does not prove production breakage, it does not
          prove runtime behaviour, and a clean compile does not prove safety. Changes of a class the
          type system cannot express — <code className="mono">maxLength</code>,{" "}
          <code className="mono">pattern</code>, <code className="mono">minimum</code>,{" "}
          <code className="mono">format</code>, enum semantics, auth, rate limits, behaviour — are
          returned as UNKNOWN, because no call site could be made to fail on them and reporting one
          as safe would be worse than reporting it as broken. The corpus is synthetic call sites
          against real vendor specs: the specifications, the diffs and the compiler are real, and
          the client code is generated.
        </p>
      </div>
    </section>
  );
}
