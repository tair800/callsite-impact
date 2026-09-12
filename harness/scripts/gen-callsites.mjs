/**
 * gen-callsites.mjs — write realistic TypeScript call sites from ONE revision of a spec.
 *
 * This script is the pre-registration device described in DECISIONS.md ADR-001. Its inputs are
 * revision **A** and an integer seed. It is never given revision B and never given the diff, so it
 * cannot choose what breaks; that choice belongs to the compiler, later, on code written before the
 * question was asked.
 *
 * Everything it varies is fixed in ADR-001's table: which operations are called, which optional
 * request properties are supplied, which response properties are read and how deeply, how a read is
 * bound (inferred const / annotated const / exhaustive switch), and how it is navigated (`a.b` or
 * `a?.b`). The binding axis is on that list for a specific reason: it is the only thing that decides
 * whether a *widening* change — a member added to a response enum — can reach a call site at all.
 * Fixing it in advance is what stops that proportion being tuned once the numbers are in.
 *
 * Types are indexed through `paths["/literal/path"]["post"]` rather than through the `operations`
 * interface. Both exist in openapi-typescript's output, but the operations key is a mangled name
 * this script would have to *guess*; the path and method are read straight out of the spec. A guess
 * that goes wrong produces a call site that fails to compile against revision A, which is silently
 * discarded — so guessing would quietly shrink the corpus instead of failing loudly.
 */

import { createHash } from "node:crypto";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { basename, extname, join } from "node:path";

import yaml from "js-yaml";

// ----------------------------------------------------------------------------- determinism

/** mulberry32: small, seeded, and identical across runs. `Math.random()` would make the corpus
 *  unreproducible, and a corpus nobody can regenerate is a corpus nobody can check. */
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

const pick = (rand, xs) => xs[Math.floor(rand() * xs.length) % xs.length];
const chance = (rand, p) => rand() < p;

/** Must agree byte for byte with `callsite_id()` in src/callsite_impact/domain.py. The two sides of
 *  this pipeline name call sites independently, and if they ever disagree the join silently empties.
 *  `tests/test_callsite_id_parity.py` pins them together. */
function callsiteId(pairId, operationKey, index) {
  const digest = createHash("sha256").update(`${pairId}|${operationKey}|${index}`).digest("hex");
  return `cs_${digest.slice(0, 12)}`;
}

// -------------------------------------------------------------------------------- schema walking

/** Resolve a local `$ref`. Remote refs are not followed: every spec in this corpus is
 *  self-contained, and following a remote one would make generation depend on the network. */
function deref(schema, root, depth = 0) {
  let seen = 0;
  while (schema && schema.$ref && seen < 50) {
    if (!schema.$ref.startsWith("#/")) return null;
    let node = root;
    for (const seg of schema.$ref.slice(2).split("/")) {
      node = node?.[seg.replace(/~1/g, "/").replace(/~0/g, "~")];
    }
    schema = node;
    seen += 1;
  }
  return schema ?? null;
}

/** Flatten the composition keywords far enough to synthesise a value.
 *
 *  `allOf` is merged because that is what it means. `oneOf`/`anyOf` collapse to the FIRST branch,
 *  deterministically — not randomly. A random branch would make the corpus depend on the seed in a
 *  way that interacts with the diff, and the whole design rests on the generator being blind to it.
 */
function flatten(schema, root, depth = 0) {
  const s = deref(schema, root);
  if (!s || depth > 12) return null;
  if (Array.isArray(s.allOf)) {
    const merged = { type: "object", properties: {}, required: [] };
    for (const part of s.allOf) {
      const f = flatten(part, root, depth + 1);
      if (!f) continue;
      Object.assign(merged.properties, f.properties ?? {});
      merged.required.push(...(f.required ?? []));
    }
    for (const [k, v] of Object.entries(s)) {
      if (k !== "allOf" && merged[k] === undefined) merged[k] = v;
    }
    if (s.properties) Object.assign(merged.properties, s.properties);
    if (s.required) merged.required.push(...s.required);
    return merged;
  }
  const branch = s.oneOf ?? s.anyOf;
  if (Array.isArray(branch) && branch.length) return flatten(branch[0], root, depth + 1);
  return s;
}

const quote = (v) => JSON.stringify(String(v));

/**
 * Synthesise a TypeScript literal that satisfies `schema`.
 *
 * Returns `null` when it cannot — a schema shape this generator does not handle. `null` is
 * deliberately not a fallback value like `{}` or `"x"`: a wrong literal compiles against revision A
 * about half the time, and the half that slips through pollutes the corpus with call sites whose
 * behaviour under revision B means nothing. Failing to produce one costs a call site; producing a
 * wrong one costs a label.
 */
function synth(schema, root, rand, depth = 0) {
  const s = flatten(schema, root);
  if (!s || depth > 6) return null;

  if (Array.isArray(s.enum) && s.enum.length) return quote(s.enum[0]);
  if (s.const !== undefined) return quote(s.const);

  const type = Array.isArray(s.type) ? s.type[0] : s.type;
  switch (type) {
    case "string":
      if (s.example !== undefined) return quote(s.example);
      if (s.format === "date-time") return quote("2026-01-15T09:30:00Z");
      if (s.format === "date") return quote("2026-01-15");
      return quote("sample-value");
    case "integer":
      return String(s.example ?? 1);
    case "number":
      return String(s.example ?? 1);
    case "boolean":
      return String(s.example ?? false);
    case "array": {
      const item = synth(s.items, root, rand, depth + 1);
      return item === null ? "[]" : `[${item}]`;
    }
    case "object":
    case undefined: {
      if (!s.properties) return s.additionalProperties === false ? "{}" : "{}";
      const required = new Set(s.required ?? []);
      const parts = [];
      for (const [name, prop] of Object.entries(s.properties)) {
        if (!required.has(name)) continue;
        const value = synth(prop, root, rand, depth + 1);
        if (value === null) return null; // a required property we cannot build: abandon the object
        parts.push(`${JSON.stringify(name)}: ${value}`);
      }
      return `{ ${parts.join(", ")} }`;
    }
    default:
      return null;
  }
}

/**
 * The properties a call site may safely read off a response, with whether each is optional.
 *
 * The subtlety is unions. `flatten` collapses `oneOf`/`anyOf` to the first branch so a *value* can
 * be synthesised, but openapi-typescript emits the response type as the union of every branch — and
 * a property present in only one branch does not exist on that union. Reading it is TS2339 against
 * revision A, and the call site is thrown away before it can ever be labelled. So when the response
 * is a union this returns the INTERSECTION of the branches: the properties that are actually there
 * whichever branch arrives.
 */
function readableProperties(schema, root) {
  const resolved = deref(schema, root);
  if (!resolved) return [];
  const branches = resolved.oneOf ?? resolved.anyOf;

  const own = (node) => {
    const f = flatten(node, root);
    if (!f || !f.properties) return null;
    const required = new Set(f.required ?? []);
    const out = new Map();
    for (const [name, prop] of Object.entries(f.properties)) {
      out.set(name, { name, optional: !required.has(name), schema: prop });
    }
    return out;
  };

  if (Array.isArray(branches) && branches.length > 1) {
    const maps = branches.map(own).filter(Boolean);
    if (!maps.length) return [];
    const [first, ...rest] = maps;
    const shared = [];
    for (const [name, info] of first) {
      if (rest.every((m) => m.has(name))) {
        // Optional in ANY branch means optional on the union.
        const optional = info.optional || rest.some((m) => m.get(name).optional);
        shared.push({ ...info, optional });
      }
    }
    return shared;
  }

  const single = own(resolved);
  return single ? [...single.values()] : [];
}

/** Of those, the ones that are themselves objects — so a call site can reach a level deeper. */
function nestedProperties(props, root) {
  return props.filter((p) => {
    const f = flatten(p.schema, root);
    return f && f.type === "object" && f.properties && Object.keys(f.properties).length > 0;
  });
}

/** A property whose schema is a string enum — the only shape an exhaustive `switch` can be written
 *  over, and therefore the only shape the widening rule can ever reach. */
function enumProperties(props, root) {
  const out = [];
  for (const prop of props) {
    const f = flatten(prop.schema, root);
    if (f && Array.isArray(f.enum) && f.enum.length >= 2 && f.enum.every((v) => typeof v === "string")) {
      out.push({ name: prop.name, members: f.enum, optional: prop.optional });
    }
  }
  return out;
}

// ------------------------------------------------------------------------------------- generation

const JSON_MEDIA = ["application/json", "application/json; charset=utf-8", "*/*"];

function jsonMediaKey(content) {
  if (!content) return null;
  for (const m of JSON_MEDIA) if (content[m]) return m;
  const first = Object.keys(content).find((k) => k.includes("json"));
  return first ?? null;
}

function successStatus(responses) {
  for (const code of ["200", "201", "202"]) if (responses?.[code]) return code;
  return null;
}

function generateOperation({ root, path, method, pairId, vendor, rand, index }) {
  const op = root.paths[path][method];
  const operationKey = `${method.toUpperCase()} ${path}`;
  const id = callsiteId(pairId, operationKey, index);

  const reqMedia = jsonMediaKey(op.requestBody?.content);
  const status = successStatus(op.responses);
  const resMedia = status ? jsonMediaKey(op.responses[status].content) : null;
  if (!reqMedia && !resMedia) return null; // nothing typed to hold on to

  const lines = [];
  const intent = { callsiteId: id, operationKey, requestProperties: [], responseProperties: [] };

  const pathType = `paths[${JSON.stringify(path)}][${JSON.stringify(method)}]`;
  const params = [];
  const body = [];

  // ---- the request half
  if (reqMedia) {
    const schema = op.requestBody.content[reqMedia].schema;
    const flat = flatten(schema, root);
    if (!flat || !flat.properties) return null;
    const required = new Set(flat.required ?? []);
    const optional = Object.keys(flat.properties).filter((n) => !required.has(n));

    // ADR-001: all required properties, plus a seeded subset of the optional ones.
    const chosenOptional = optional.filter(() => chance(rand, 0.25)).slice(0, 6);
    const include = [...required, ...chosenOptional];

    const parts = [];
    for (const name of include) {
      const value = synth(flat.properties[name], root, rand, 1);
      if (value === null) {
        if (required.has(name)) return null; // cannot build a valid body at all
        continue;
      }
      parts.push({ name, value });
      intent.requestProperties.push({ path: [name] });
    }
    if (!parts.length) return null;

    // `NonNullable` is not decoration: openapi-typescript marks `requestBody` optional, so indexing
    // straight into `["content"]` reports TS2339 and every call site in the file is discarded.
    const reqType = `NonNullable<${pathType}["requestBody"]>["content"][${JSON.stringify(reqMedia)}]`;
    lines.push(`  const body: ${reqType} = {`);
    for (const p of parts) lines.push(`    ${JSON.stringify(p.name)}: ${p.value},`);
    lines.push(`  };`);
    body.push("body");
  }

  // ---- the response half
  if (resMedia) {
    const resType = `${pathType}["responses"][${JSON.stringify(status)}]["content"][${JSON.stringify(resMedia)}]`;
    params.push(`res: ${resType}`);
    const schema = op.responses[status].content[resMedia].schema;
    const props = readableProperties(schema, root);
    const nested = new Map(nestedProperties(props, root).map((p) => [p.name, p]));
    const enums = enumProperties(props, root);

    let reads = 0;
    for (const prop of props) {
      if (reads >= 4) break;
      if (!chance(rand, 0.5)) continue;
      const deeper = nested.has(prop.name) && chance(rand, 0.4);
      // An optional parent MUST be navigated with `?.` or the read is TS18048 against revision A
      // and the whole call site is discarded before it can carry a label. Where the parent is
      // required the choice is free, and ADR-001 says vary it.
      const optionalChained = prop.optional || chance(rand, 0.35);
      const dot = optionalChained ? "?." : ".";
      if (deeper) {
        const inner = flatten(nested.get(prop.name).schema, root);
        const innerName = Object.keys(inner.properties)[0];
        lines.push(`  const read_${reads} = res${dot}${prop.name}${dot}${innerName};`);
        intent.responseProperties.push({ path: [prop.name, innerName], optionalChained });
      } else {
        lines.push(`  const read_${reads} = res${dot}${prop.name};`);
        intent.responseProperties.push({ path: [prop.name], optionalChained });
      }
      body.push(`read_${reads}`);
      reads += 1;
    }

    // ADR-001's binding axis. These two pin the narrow type; the inferred `const` above does not,
    // which is exactly why a widening change reaches one shape of call site and not the other.
    if (enums.length && chance(rand, 0.5)) {
      const e = pick(rand, enums);
      const union = e.members.map((m) => quote(m)).join(" | ");
      if (chance(rand, 0.5)) {
        // `| undefined` when the property is optional — the annotation has to admit what the
        // response type actually says, or it fails against revision A and proves nothing.
        const annotation = e.optional ? `${union} | undefined` : union;
        lines.push(`  const pinned: ${annotation} = res.${e.name};`);
        body.push("pinned");
      } else {
        lines.push(`  switch (res.${e.name}) {`);
        for (const m of e.members) lines.push(`    case ${quote(m)}: break;`);
        if (e.optional) lines.push(`    case undefined: break;`);
        lines.push(`    default: { const exhaustive: never = res.${e.name}; return exhaustive; }`);
        lines.push(`  }`);
      }
      intent.responseProperties.push({ path: [e.name], optionalChained: false });
    }
  }

  if (!lines.length) return null;

  const marker = `// @callsite id=${id} op=${method.toUpperCase()} ${path} key=${method}${path}`;
  const source = [
    marker,
    `export function ${id}(${params.join(", ")}): unknown {`,
    ...lines,
    `  return [${body.join(", ")}];`,
    `}`,
    ``,
  ].join("\n");

  return { id, operationKey, source, intent, vendor, pairId };
}

// -------------------------------------------------------------------------------------------- CLI

function arg(name, fallback = null) {
  const i = process.argv.indexOf(`--${name}`);
  if (i === -1) return fallback;
  return process.argv[i + 1];
}

function main() {
  const specPath = arg("spec");
  const outDir = arg("out");
  const pairId = arg("pair");
  const vendor = arg("vendor", "unknown");
  const seed = Number(arg("seed", "1"));
  const maxOperations = Number(arg("max-operations", "40"));
  const perOperation = Number(arg("per-operation", "3"));

  if (!specPath || !outDir || !pairId) {
    console.error(
      "usage: node gen-callsites.mjs --spec <A.json> --out <dir> --pair <id> [--vendor v] " +
        "[--seed n] [--max-operations n] [--per-operation n]",
    );
    process.exit(2);
  }

  // Half this corpus is YAML and half is JSON. `openapi-typescript` reads both, so a generator that
  // read only JSON would silently exclude every YAML vendor from the corpus — which is the kind of
  // gap that shows up as "we only had two vendors" and never as an error.
  const text = readFileSync(specPath, "utf8");
  const root = extname(specPath).toLowerCase() === ".json" ? JSON.parse(text) : yaml.load(text);
  if (!root.paths) {
    console.error(`no paths in ${specPath}`);
    process.exit(1);
  }

  const rand = rng(seed);
  const operations = [];
  for (const path of Object.keys(root.paths).sort()) {
    for (const method of ["get", "post", "put", "patch", "delete"]) {
      if (root.paths[path]?.[method]) operations.push({ path, method });
    }
  }

  // A seeded sample. The first version of this line was `filter(() => chance(rand, 1))`, which is
  // always true — so it took the first N operations in sorted path order and called it a sample.
  // On a specification with 500 paths that means every call site lands in the alphabetical head of
  // the API, and whether a change is covered depends on its first letter. Shuffled with the same
  // seeded generator instead, which is what ADR-001 says this axis is.
  const shuffled = [...operations];
  for (let i = shuffled.length - 1; i > 0; i -= 1) {
    const j = Math.floor(rand() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }
  const selected = shuffled.slice(0, maxOperations);

  mkdirSync(outDir, { recursive: true });
  const emitted = [];
  const shapes = new Set();
  let index = 0;
  let duplicates = 0;
  for (const { path, method } of selected) {
    for (let k = 0; k < perOperation; k += 1) {
      const gen = generateOperation({ root, path, method, pairId, vendor, rand, index });
      index += 1;
      if (!gen) continue;
      // An operation whose properties are ALL required has exactly one call site in it, and the
      // seeded subset draws the same one every time. Emitting it three times would triple whatever
      // the compiler says about it and inflate every count that follows. Identical bodies are
      // dropped, and the drop is reported rather than hidden.
      const shape = createHash("sha256")
        .update(gen.source.replace(/cs_[0-9a-f]{12}/g, "ID"))
        .digest("hex");
      if (shapes.has(shape)) {
        duplicates += 1;
        continue;
      }
      shapes.add(shape);
      emitted.push(gen);
    }
  }

  if (!emitted.length) {
    console.error(`generated nothing from ${basename(specPath)} — the spec shape is unsupported`);
    process.exit(1);
  }

  const header = [
    `// GENERATED from revision A of ${basename(specPath)} — pair ${pairId}, seed ${seed}.`,
    `// Written without sight of revision B or of any diff. See DECISIONS.md ADR-001.`,
    `import type { paths } from "./spec";`,
    ``,
  ].join("\n");

  writeFileSync(join(outDir, "callsites.ts"), header + emitted.map((e) => e.source).join("\n"), "utf8");
  writeFileSync(
    join(outDir, "intent.json"),
    JSON.stringify(
      { pairId, vendor, seed, spec: basename(specPath), callsites: emitted.map((e) => e.intent) },
      null,
      2,
    ),
    "utf8",
  );

  console.log(
    `${emitted.length} call sites from ${selected.length} operations ` +
      `(${duplicates} identical shapes dropped) -> ${outDir}`,
  );
}

main();
