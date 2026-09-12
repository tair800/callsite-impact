#!/usr/bin/env node
// run-tsc.mjs — THE ORACLE. The only thing in this repository that produces ground truth.
//
// It typechecks a directory of generated call sites against one revision's generated types and
// writes every diagnostic out as data. Run it twice — once with revision A's types, once with
// revision B's — and the difference is the answer key the classifier is graded against.
//
// Two properties are load-bearing and easy to lose:
//
//   1. It reports EVERY diagnostic. No first-error stop, no cap, no dedupe. A truncated answer key
//      silently converts real breakages into false negatives in the score, which is the one error
//      this project exists to measure.
//   2. It reads diagnostics through the compiler API, not by parsing tsc's stdout. Diagnostic
//      messages routinely contain newlines and commas (every "Type 'X' is not assignable to type
//      'Y'" chain does), so line-oriented parsing of the text output loses or mangles them.
//
// A non-zero exit here means the harness itself failed. Type errors are the product, not a failure:
// they leave the exit code at 0 and land in the output file.
//
// Usage: node run-tsc.mjs --types <types.ts> --callsites <dir> --out <labels.json>

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";

const HARNESS_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** Call sites `import type { operations } from "./spec"`, so the types land under this name. */
const SPEC_MODULE_BASENAME = "spec.ts";

/**
 * Parse `--flag value` pairs. Hand-rolled because the harness carries no argument-parsing
 * dependency: every package here is one the oracle's result depends on, and that list stays short.
 *
 * @param {string[]} argv Arguments after the script name.
 * @returns {Record<string, string>} Flag name without dashes to value.
 */
function parseArgs(argv) {
  /** @type {Record<string, string>} */
  const out = {};
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (!token.startsWith("--")) continue;
    const eq = token.indexOf("=");
    if (eq !== -1) {
      out[token.slice(2, eq)] = token.slice(eq + 1);
    } else {
      out[token.slice(2)] = argv[i + 1] ?? "";
      i += 1;
    }
  }
  return out;
}

/**
 * Read the committed compiler options.
 *
 * Kept in `tsconfig.base.json` rather than inline here so that the settings which decide what counts
 * as a breakage are reviewable in a diff on their own.
 *
 * @returns {Record<string, unknown>} The raw `compilerOptions` object.
 */
function readBaseCompilerOptions() {
  const basePath = path.join(HARNESS_ROOT, "tsconfig.base.json");
  const raw = ts.readConfigFile(basePath, ts.sys.readFile);
  if (raw.error) {
    throw new Error(
      `run-tsc: cannot read ${basePath}: ${ts.flattenDiagnosticMessageText(raw.error.messageText, " ")}`,
    );
  }
  return raw.config.compilerOptions ?? {};
}

/**
 * Put the revision's types where the call sites import them from.
 *
 * The types file is copied into the call-site directory rather than the call sites being copied next
 * to the types, so that the file paths in the diagnostics are the real call-site paths. Those paths
 * are the anchor every verdict is joined on; a path pointing into a scratch copy cannot be checked
 * by a reader.
 *
 * @param {string} typesPath Absolute path to the generated types module.
 * @param {string} callsitesDir Absolute path to the call-site directory.
 */
function installTypes(typesPath, callsitesDir) {
  const destination = path.join(callsitesDir, SPEC_MODULE_BASENAME);
  if (path.resolve(typesPath) === destination) return;
  fs.copyFileSync(typesPath, destination);
}

/**
 * Collect every TypeScript file the program should contain.
 *
 * @param {string} dir Absolute directory to scan.
 * @returns {string[]} Absolute paths, sorted, so the program is built identically on every run.
 */
function collectTypeScriptFiles(dir) {
  /** @type {string[]} */
  const found = [];
  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules") continue;
        walk(full);
      } else if (entry.name.endsWith(".ts") || entry.name.endsWith(".tsx")) {
        found.push(full);
      }
    }
  };
  walk(dir);
  return found.sort();
}

/**
 * Turn one diagnostic into the flat record the Python side consumes.
 *
 * Diagnostics without a file (configuration-level errors) are kept with a null file and zeroed
 * position rather than dropped, because dropping them would let a broken run look like a clean one.
 *
 * @param {import("typescript").Diagnostic} diagnostic
 * @param {string} callsitesDir Absolute directory the file paths are reported relative to.
 * @returns {{file: string|null, line: number, column: number, code: string, message: string}}
 */
function toRecord(diagnostic, callsitesDir) {
  const message = ts.flattenDiagnosticMessageText(diagnostic.messageText, "\n");
  const code = `TS${diagnostic.code}`;
  if (!diagnostic.file || diagnostic.start === undefined) {
    return { file: null, line: 0, column: 0, code, message };
  }
  const { line, character } = diagnostic.file.getLineAndCharacterOfPosition(diagnostic.start);
  const relative = path.relative(callsitesDir, diagnostic.file.fileName).split(path.sep).join("/");
  // tsc reports 1-based line and column to humans; the compiler API is 0-based. Emit the 1-based
  // numbers, because every anchor in this project is something a reader opens an editor at.
  return { file: relative, line: line + 1, column: character + 1, code, message };
}

function main(argv) {
  const args = parseArgs(argv);
  const typesArg = args.types;
  const callsitesArg = args.callsites;
  const outArg = args.out;
  if (!typesArg || !callsitesArg || !outArg) {
    process.stderr.write(
      "usage: node run-tsc.mjs --types <types.ts> --callsites <dir> --out <labels.json>\n",
    );
    return 2;
  }

  const typesPath = path.resolve(typesArg);
  const callsitesDir = path.resolve(callsitesArg);
  const outPath = path.resolve(outArg);

  if (!fs.existsSync(typesPath)) {
    process.stderr.write(`run-tsc: types file not found: ${typesPath}\n`);
    return 2;
  }
  if (!fs.existsSync(callsitesDir) || !fs.statSync(callsitesDir).isDirectory()) {
    process.stderr.write(`run-tsc: call-site directory not found: ${callsitesDir}\n`);
    return 2;
  }

  // Counted BEFORE the types module is installed. installTypes writes spec.ts into this directory,
  // so a count taken afterwards can never be zero: a call-site directory holding nothing at all
  // would typecheck the types module against itself, report no diagnostics, and hand back an empty
  // answer key that is indistinguishable from a clean revision. That is precisely the silent false
  // negative this script exists to prevent, so an empty directory is a harness failure.
  const callsiteFiles = collectTypeScriptFiles(callsitesDir).filter(
    (file) => path.basename(file) !== SPEC_MODULE_BASENAME,
  );
  if (callsiteFiles.length === 0) {
    process.stderr.write(`run-tsc: no call-site .ts files under ${callsitesDir}\n`);
    return 2;
  }

  installTypes(typesPath, callsitesDir);

  const compilerOptions = readBaseCompilerOptions();
  const configObject = { compilerOptions, include: ["**/*.ts"] };
  const configPath = path.join(callsitesDir, "tsconfig.json");
  // Written to disk as well as used in-process: the run is then reproducible by hand, and a reader
  // who doubts a label can re-derive it with `npx tsc -p <callsites-dir>`.
  fs.writeFileSync(configPath, `${JSON.stringify(configObject, null, 2)}\n`, "utf8");

  const parsed = ts.parseJsonConfigFileContent(configObject, ts.sys, callsitesDir, undefined, configPath);
  if (parsed.errors.length > 0) {
    for (const error of parsed.errors) {
      process.stderr.write(
        `run-tsc: bad compiler options: ${ts.flattenDiagnosticMessageText(error.messageText, " ")}\n`,
      );
    }
    return 1;
  }

  // Re-scanned rather than reusing callsiteFiles, because the program must also contain the spec.ts
  // that installTypes just wrote.
  const rootNames = collectTypeScriptFiles(callsitesDir);

  const program = ts.createProgram({ rootNames, options: parsed.options });
  const diagnostics = ts.getPreEmitDiagnostics(program);

  const errors = diagnostics
    .map((diagnostic) => toRecord(diagnostic, callsitesDir))
    .sort(
      (a, b) =>
        (a.file ?? "").localeCompare(b.file ?? "") ||
        a.line - b.line ||
        a.column - b.column ||
        a.code.localeCompare(b.code),
    );

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(
    outPath,
    `${JSON.stringify({ errors, errorCount: errors.length }, null, 2)}\n`,
    "utf8",
  );

  process.stderr.write(
    `run-tsc: ${rootNames.length} file(s), ${errors.length} diagnostic(s) -> ${outPath}\n`,
  );
  return 0;
}

process.exit(main(process.argv.slice(2)));
