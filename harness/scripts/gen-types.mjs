#!/usr/bin/env node
// gen-types.mjs — turn one OpenAPI document into one TypeScript type module.
//
// Deliberately a thin shell around the pinned `openapi-typescript` binary. The point of this stage
// is that nothing in this repository decides what a spec means in TypeScript: a third-party,
// deterministic generator does, at a version pinned in package.json. If this file grew a
// transformation of its own, the oracle would be partly ours, and the whole measurement would be
// arguing with itself.
//
// Usage: node gen-types.mjs <specPath> <outTsPath>

import { spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);

/** Markers the generated module must contain, or downstream stages have nothing to index into. */
// `paths` only. openapi-typescript emits an `operations` interface only when the specification
// gives its operations an `operationId`, and several real specifications in this corpus -- every
// Twilio "before" revision, for one -- do not. Call sites are generated against
// `paths["/literal"]["post"]`, which is always present, so requiring `operations` here rejected
// four usable vendors' worth of specification for a symbol nothing reads.
const REQUIRED_EXPORTS = ["export interface paths"];

/**
 * Locate the pinned CLI entry point inside node_modules.
 *
 * Resolved through `require.resolve` rather than invoked as `npx openapi-typescript`, because npx
 * is free to fetch a different version from the network and this stage must be reproducible offline
 * at exactly the version the lockfile pins.
 *
 * @returns {string} Absolute path to the generator's CLI script.
 */
function resolveGeneratorCli() {
  const manifestPath = require.resolve("openapi-typescript/package.json");
  const manifest = JSON.parse(fs.readFileSync(manifestPath, "utf8"));
  const binField = manifest.bin;
  const relative =
    typeof binField === "string" ? binField : binField?.["openapi-typescript"] ?? binField?.oats;
  if (!relative) {
    throw new Error(`openapi-typescript ${manifest.version} declares no usable "bin" entry`);
  }
  return path.join(path.dirname(manifestPath), relative);
}

function main(argv) {
  const [specPath, outTsPath] = argv;
  if (!specPath || !outTsPath) {
    process.stderr.write("usage: node gen-types.mjs <specPath> <outTsPath>\n");
    return 2;
  }

  const specAbs = path.resolve(specPath);
  const outAbs = path.resolve(outTsPath);
  if (!fs.existsSync(specAbs)) {
    process.stderr.write(`gen-types: spec not found: ${specAbs}\n`);
    return 2;
  }
  fs.mkdirSync(path.dirname(outAbs), { recursive: true });

  const cli = resolveGeneratorCli();
  // Spawn node on the CLI script directly. The .cmd shim npm installs on Windows needs a shell, and
  // shelling out means quoting rules decide whether a path with a space works.
  const result = spawnSync(process.execPath, [cli, specAbs, "--output", outAbs], {
    stdio: ["ignore", "inherit", "inherit"],
  });

  if (result.error) {
    process.stderr.write(`gen-types: failed to start generator: ${result.error.message}\n`);
    return 1;
  }
  if (result.status !== 0) {
    process.stderr.write(
      `gen-types: generator exited ${result.status} for ${specAbs} (see error above)\n`,
    );
    return result.status ?? 1;
  }

  // A zero exit with an empty or shapeless file would poison every later stage silently, so the
  // contract the rest of the harness relies on is checked here rather than assumed.
  if (!fs.existsSync(outAbs)) {
    process.stderr.write(`gen-types: generator reported success but wrote no ${outAbs}\n`);
    return 1;
  }
  const contents = fs.readFileSync(outAbs, "utf8");
  const missing = REQUIRED_EXPORTS.filter((marker) => !contents.includes(marker));
  if (missing.length > 0) {
    process.stderr.write(
      `gen-types: ${outAbs} is missing ${missing.join(", ")} — the spec may have no operations\n`,
    );
    return 1;
  }

  process.stderr.write(`gen-types: ${specAbs} -> ${outAbs} (${contents.length} bytes)\n`);
  return 0;
}

process.exit(main(process.argv.slice(2)));
