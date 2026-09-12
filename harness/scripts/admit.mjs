/**
 * admit.mjs — keep only the call sites that typecheck clean against revision A.
 *
 * ADR-001: *"A call site that does not compile against A is discarded, never repaired."* This is the
 * script that discards them, and it exists because the generator is imperfect on purpose. Making the
 * generator handle every schema shape in every vendor's specification is weeks of work whose only
 * product is a larger corpus; dropping what it got wrong costs a call site and costs nothing else.
 *
 * The important property is that discarding happens **before revision B is ever consulted**. A call
 * site is admitted or rejected on evidence from A alone, so the admitted set cannot have been shaped
 * by what breaks later. Repairing instead of discarding would destroy exactly that property: the
 * repair would be written by someone who could look at the diff.
 *
 * The discard count and the reason for every discard are written out, because a corpus that quietly
 * shrinks is a corpus whose denominator nobody can check.
 */

import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import ts from "typescript";

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  return i === -1 ? fallback : process.argv[i + 1];
}

const MARKER = /^\/\/ @callsite id=(cs_[0-9a-f]{12}) /;

/** Split the file into its header and one block per call site, keyed by id. */
function parseBlocks(source) {
  const lines = source.split("\n");
  const header = [];
  const blocks = [];
  let current = null;
  for (const line of lines) {
    const m = MARKER.exec(line);
    if (m) {
      if (current) blocks.push(current);
      current = { id: m[1], lines: [line] };
      continue;
    }
    if (current) current.lines.push(line);
    else header.push(line);
  }
  if (current) blocks.push(current);
  return { header: header.join("\n"), blocks };
}

function compile(dir, fileName) {
  const options = {
    strict: true,
    noEmit: true,
    target: ts.ScriptTarget.ES2022,
    module: ts.ModuleKind.ESNext,
    moduleResolution: ts.ModuleResolutionKind.Bundler,
    skipLibCheck: true,
  };
  const program = ts.createProgram([join(dir, fileName)], options);
  return ts.getPreEmitDiagnostics(program).filter((d) => d.file && d.start !== undefined);
}

function main() {
  const callsitesPath = arg("callsites");
  const typesPath = arg("types");
  const outDir = arg("out");
  const maxRounds = Number(arg("max-rounds", "6"));
  if (!callsitesPath || !typesPath || !outDir) {
    console.error("usage: node admit.mjs --callsites <callsites.ts> --types <A.ts> --out <dir>");
    process.exit(2);
  }

  mkdirSync(outDir, { recursive: true });
  writeFileSync(join(outDir, "spec.ts"), readFileSync(typesPath, "utf8"), "utf8");

  const { header, blocks } = parseBlocks(readFileSync(callsitesPath, "utf8"));
  let kept = blocks;
  const discarded = [];

  for (let round = 0; round < maxRounds; round += 1) {
    const body = kept.map((b) => b.lines.join("\n")).join("\n");
    const text = `${header}\n${body}\n`;
    writeFileSync(join(outDir, "callsites.ts"), text, "utf8");

    const diagnostics = compile(outDir, "callsites.ts");
    if (!diagnostics.length) {
      writeFileSync(
        join(outDir, "admission.json"),
        JSON.stringify(
          {
            generated: blocks.length,
            admitted: kept.length,
            discarded: discarded.length,
            rounds: round + 1,
            discards: discarded,
          },
          null,
          2,
        ),
        "utf8",
      );
      console.log(
        `admitted ${kept.length}/${blocks.length} call sites ` +
          `(${discarded.length} discarded over ${round + 1} round(s))`,
      );
      return;
    }

    // Map every diagnostic back to the call site whose block contains it.
    const offending = new Map();
    const fileText = text.split("\n");
    for (const d of diagnostics) {
      const { line } = d.file.getLineAndCharacterOfPosition(d.start);
      let owner = null;
      for (let i = line; i >= 0; i -= 1) {
        const m = MARKER.exec(fileText[i] ?? "");
        if (m) {
          owner = m[1];
          break;
        }
      }
      if (!owner) {
        console.error(
          `a diagnostic landed outside every call site block at line ${line + 1}: ` +
            ts.flattenDiagnosticMessageText(d.messageText, " "),
        );
        process.exit(1);
      }
      if (!offending.has(owner)) {
        offending.set(owner, {
          callsiteId: owner,
          code: `TS${d.code}`,
          message: ts.flattenDiagnosticMessageText(d.messageText, " ").slice(0, 300),
        });
      }
    }

    discarded.push(...offending.values());
    const drop = new Set(offending.keys());
    kept = kept.filter((b) => !drop.has(b.id));

    if (!kept.length) {
      console.error("every generated call site failed against revision A");
      process.exit(1);
    }
  }

  console.error(`still not clean against revision A after ${maxRounds} rounds`);
  process.exit(1);
}

main();
