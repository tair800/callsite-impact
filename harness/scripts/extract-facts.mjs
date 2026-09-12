#!/usr/bin/env node
// extract-facts.mjs — PARSER ONLY, AND THAT IS THE POINT.
//
// This script is allowed exactly one TypeScript capability: building a syntax tree with
// `ts.createSourceFile` and walking it. Every type-aware compiler API is forbidden here — anything
// that builds a compilation unit, anything that hands back a type resolver, anything that reports
// type errors. A guard test in the Python suite greps this file for those identifiers and fails the
// build if one appears.
//
// The reason is not tidiness. What this script emits is the *input* to the classifier, and the
// classifier is the system under test. The answer key for that test is what the compiler says.
// A fact extractor that could consult the compiler would be handing the system under test its own
// answer key, and every number downstream — false-negative rate above all — would be measuring
// nothing. The separation is the experiment.
//
// So everything below is syntax: identifier spelling, source positions, the literal text of a type
// annotation. Never what a type resolves to. Where syntax cannot answer (a computed property key, a
// dynamic index, a value flowing through a function call), this script records nothing rather than
// guessing, and the resulting gap is a real limitation of the approach, not a bug to paper over.
//
// Usage: node extract-facts.mjs --callsites <dir> --out <facts.json>
//        optional: --response-param <name,name>  --request-var <name,name>

import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

/**
 * The identity line the generator writes immediately above each generated function.
 *
 * Identity comes from this marker rather than from anything inferred, because the call-site id has
 * to match the one the generator minted or the facts cannot be joined to the compiler's labels.
 * Shape: `// @callsite id=cs_abc123def456 op=POST /payments key=post-payments`
 */
const MARKER = /^\s*\/\/\s*@callsite\s+id=(\S+)\s+op=(.+?)\s+key=(\S+)\s*$/;

/** Parameter names taken to hold the operation's response when no annotation gives it away. */
const DEFAULT_RESPONSE_NAMES = ["response", "res", "result"];

/** Variable names taken to hold the request body when no annotation gives it away. */
const DEFAULT_REQUEST_NAMES = ["body", "requestBody", "payload", "request"];

/** Files that are never call sites: the generated types module and any declaration file. */
const SKIPPED_FILES = new Set(["spec.ts"]);

/**
 * Parse `--flag value` pairs. Hand-rolled to keep this script's dependency list at exactly one.
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
 * @param {string} dir Absolute directory to scan.
 * @returns {string[]} Absolute paths of candidate call-site files, sorted for run-to-run stability.
 */
function collectCallsiteFiles(dir) {
  /** @type {string[]} */
  const found = [];
  const walk = (current) => {
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const full = path.join(current, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules") continue;
        walk(full);
      } else if (
        entry.name.endsWith(".ts") &&
        !entry.name.endsWith(".d.ts") &&
        !SKIPPED_FILES.has(entry.name)
      ) {
        found.push(full);
      }
    }
  };
  walk(dir);
  return found.sort();
}

/**
 * Strip syntax that wraps an expression without changing what it names.
 *
 * @param {import("typescript").Node} node
 * @returns {import("typescript").Node}
 */
function unwrap(node) {
  let current = node;
  for (;;) {
    if (
      ts.isParenthesizedExpression(current) ||
      ts.isNonNullExpression(current) ||
      ts.isAsExpression(current) ||
      ts.isSatisfiesExpression(current)
    ) {
      current = current.expression;
      continue;
    }
    return current;
  }
}

/**
 * @param {import("typescript").SourceFile} sourceFile
 * @param {import("typescript").Node} node
 * @returns {{line: number, column: number}} 1-based, matching how the compiler reports positions.
 */
function positionOf(sourceFile, node) {
  const { line, character } = sourceFile.getLineAndCharacterOfPosition(node.getStart(sourceFile));
  return { line: line + 1, column: character + 1 };
}

/**
 * The statically known spelling of a property key, or null when only execution would reveal it.
 *
 * @param {import("typescript").PropertyName} name
 * @returns {string | null}
 */
function propertyKey(name) {
  if (ts.isIdentifier(name) || ts.isPrivateIdentifier(name)) return name.text;
  if (ts.isStringLiteral(name) || ts.isNumericLiteral(name)) return name.text;
  return null;
}

/**
 * The literal a call site passed, as source text.
 *
 * Only string and numeric literals are captured. Anything else — a variable, a call, a computed
 * expression — has no value at parse time, and a made-up one would send an enum-member verdict to a
 * call site on evidence that does not exist.
 *
 * @param {import("typescript").Node} expression
 * @returns {string | null}
 */
function literalValue(expression) {
  const node = unwrap(expression);
  if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
  if (ts.isNumericLiteral(node)) return node.text;
  if (
    ts.isPrefixUnaryExpression(node) &&
    node.operator === ts.SyntaxKind.MinusToken &&
    ts.isNumericLiteral(node.operand)
  ) {
    return `-${node.operand.text}`;
  }
  return null;
}

/**
 * The source text of a type annotation, used only as text.
 *
 * The generator writes annotations like `operations["post-payments"]["requestBody"]`, so the word
 * `requestBody` appearing in the annotation's characters identifies the request body without
 * anything resolving that type. Reading the spelling is parsing; reading the meaning would not be.
 *
 * @param {import("typescript").Node | undefined} typeNode
 * @param {import("typescript").SourceFile} sourceFile
 * @returns {string}
 */
function annotationText(typeNode, sourceFile) {
  return typeNode ? typeNode.getText(sourceFile) : "";
}

/**
 * Walk a node's whole subtree.
 *
 * @param {import("typescript").Node} node
 * @param {(node: import("typescript").Node) => void} visit
 */
function forEachDescendant(node, visit) {
  node.forEachChild((child) => {
    visit(child);
    forEachDescendant(child, visit);
  });
}

// ------------------------------------------------------------------------------- request body side

/**
 * Find the object literal(s) that form the request body, best evidence first.
 *
 * The tiers exist because the evidence is of different quality and mixing them would hide that:
 * an annotation naming `requestBody` is near-certain, a conventional variable name is a convention,
 * and a lone object literal is a guess that is only made when there is nothing to confuse it with.
 *
 * @param {import("typescript").Node} body Function body to search.
 * @param {import("typescript").SourceFile} sourceFile
 * @param {string[]} requestNames Variable names treated as holding the body.
 * @returns {import("typescript").ObjectLiteralExpression[]}
 */
function findRequestBodyLiterals(body, sourceFile, requestNames) {
  /** @type {import("typescript").ObjectLiteralExpression[][]} */
  const tiers = [[], [], []];

  forEachDescendant(body, (node) => {
    if (ts.isVariableDeclaration(node) && node.initializer) {
      const initializer = unwrap(node.initializer);
      if (!ts.isObjectLiteralExpression(initializer)) return;
      if (annotationText(node.type, sourceFile).includes("requestBody")) {
        tiers[0].push(initializer);
        return;
      }
      if (ts.isIdentifier(node.name) && requestNames.includes(node.name.text)) {
        tiers[1].push(initializer);
      }
      return;
    }
    if (ts.isSatisfiesExpression(node) || ts.isAsExpression(node)) {
      const inner = unwrap(node.expression);
      if (
        ts.isObjectLiteralExpression(inner) &&
        annotationText(node.type, sourceFile).includes("requestBody")
      ) {
        tiers[0].push(inner);
      }
      return;
    }
    if (ts.isObjectLiteralExpression(node)) {
      tiers[2].push(node);
    }
  });

  if (tiers[0].length > 0) return tiers[0];
  if (tiers[1].length > 0) return tiers[1];
  // Only accept the weakest evidence when it is unambiguous: several bare object literals in one
  // function give no syntactic reason to prefer any of them, and picking one would be invention.
  const topLevel = tiers[2].filter((literal) => !hasObjectLiteralAncestorWithin(literal, body));
  return topLevel.length === 1 ? topLevel : [];
}

/**
 * @param {import("typescript").Node} node
 * @param {import("typescript").Node} limit Ancestor to stop at.
 * @returns {boolean} True when the node is nested inside another object literal below `limit`.
 */
function hasObjectLiteralAncestorWithin(node, limit) {
  let current = node.parent;
  while (current && current !== limit) {
    if (ts.isObjectLiteralExpression(current)) return true;
    current = current.parent;
  }
  return false;
}

/**
 * Record every property key set inside a request-body object literal, as nested paths.
 *
 * Intermediate keys are recorded as well as leaves: `{billingAddress: {city: "x"}}` yields both
 * `["billingAddress"]` and `["billingAddress", "city"]`, because removing either one breaks this
 * call site and the classifier has to be able to see both.
 *
 * Array literals contribute no path segment — `{lineItems: [{id: "1"}]}` yields
 * `["lineItems", "id"]` — because the index is a position in the client's data, not in the schema.
 *
 * @param {import("typescript").ObjectLiteralExpression} literal
 * @param {string[]} prefix
 * @param {import("typescript").SourceFile} sourceFile
 * @param {Array<{path: string[], line: number, column: number, literalValue: string | null}>} out
 */
function collectRequestProperties(literal, prefix, sourceFile, out) {
  for (const property of literal.properties) {
    if (ts.isPropertyAssignment(property)) {
      const key = propertyKey(property.name);
      if (key === null) continue;
      const propertyPath = [...prefix, key];
      const { line, column } = positionOf(sourceFile, property.name);
      out.push({ path: propertyPath, line, column, literalValue: literalValue(property.initializer) });
      descendRequestValue(property.initializer, propertyPath, sourceFile, out);
      continue;
    }
    if (ts.isShorthandPropertyAssignment(property)) {
      const { line, column } = positionOf(sourceFile, property.name);
      out.push({ path: [...prefix, property.name.text], line, column, literalValue: null });
      continue;
    }
    // Spread elements are skipped on purpose: what a spread contributes is not visible in syntax.
  }
}

/**
 * @param {import("typescript").Expression} expression
 * @param {string[]} prefix
 * @param {import("typescript").SourceFile} sourceFile
 * @param {Array<{path: string[], line: number, column: number, literalValue: string | null}>} out
 */
function descendRequestValue(expression, prefix, sourceFile, out) {
  const value = unwrap(expression);
  if (ts.isObjectLiteralExpression(value)) {
    collectRequestProperties(value, prefix, sourceFile, out);
    return;
  }
  if (ts.isArrayLiteralExpression(value)) {
    for (const element of value.elements) {
      descendRequestValue(element, prefix, sourceFile, out);
    }
  }
}

// ---------------------------------------------------------------------------------- response side

/**
 * Flatten a property-access chain into its root identifier and its links.
 *
 * Returns null when the root cannot be reached by syntax alone — a call in the middle, a literal
 * receiver — because without a named root there is no way to know the chain belongs to the response
 * at all.
 *
 * A dynamic index (`res.additionalData[key]`) is different: it makes everything *outside* it
 * unnameable, but the segments between it and the root are still perfectly readable. Those outer
 * links are dropped and the walk continues inward, so `additionalData` is still recorded as read.
 *
 * @param {import("typescript").Node} node Outermost node of the chain.
 * @returns {{root: string, links: Array<{name: string | null, node: import("typescript").Node, optional: boolean}>, truncated: boolean} | null}
 */
function flattenAccessChain(node) {
  /** @type {Array<{name: string | null, node: import("typescript").Node, optional: boolean}>} */
  const links = [];
  let truncated = false;
  let current = node;
  for (;;) {
    current = unwrap(current);
    if (ts.isPropertyAccessExpression(current)) {
      links.push({
        name: current.name.text,
        node: current.name,
        optional: current.questionDotToken !== undefined,
      });
      current = current.expression;
      continue;
    }
    if (ts.isElementAccessExpression(current)) {
      const argument = unwrap(current.argumentExpression);
      const optional = current.questionDotToken !== undefined;
      if (ts.isStringLiteral(argument) || ts.isNoSubstitutionTemplateLiteral(argument)) {
        links.push({ name: argument.text, node: argument, optional });
      } else if (ts.isNumericLiteral(argument)) {
        // An array index names a position in the data, not a property in the schema: it carries the
        // optional flag onwards but adds no segment to the path.
        links.push({ name: null, node: argument, optional });
      } else {
        // Opaque index: nothing outside this point can be named, but the inner links can.
        links.length = 0;
        truncated = true;
      }
      current = current.expression;
      continue;
    }
    if (ts.isIdentifier(current)) {
      links.reverse();
      return { root: current.text, links, truncated };
    }
    return null;
  }
}

/**
 * @param {import("typescript").Node} node
 * @returns {boolean} True when this node is the receiver of a longer chain, so an outer visit owns it.
 */
function isInnerLinkOfChain(node) {
  const parent = node.parent;
  if (!parent) return false;
  if (
    ts.isParenthesizedExpression(parent) ||
    ts.isNonNullExpression(parent) ||
    ts.isAsExpression(parent) ||
    ts.isSatisfiesExpression(parent)
  ) {
    return isInnerLinkOfChain(parent);
  }
  if (ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent)) {
    return parent.expression === node;
  }
  return false;
}

/**
 * Identify the names that stand for the operation's response inside one function.
 *
 * Three sources, all syntactic: a parameter whose annotation text mentions `responses`, a parameter
 * with a conventional name, and a local `const` whose annotation mentions `responses`. Aliases are
 * then followed to a fixed point, so `const address = response.billingAddress` makes `address` a
 * root carrying the prefix `["billingAddress"]`. Without that, the bindings ADR-001 lets the
 * generator vary would make the reads invisible here and understate what the call site touches.
 *
 * No flow analysis: reassignment, conditional binding and values crossing a function boundary are
 * not tracked, and reads through them are simply absent from the output.
 *
 * @param {import("typescript").SignatureDeclarationBase} fn
 * @param {import("typescript").Node} body
 * @param {import("typescript").SourceFile} sourceFile
 * @param {string[]} responseNames
 * @returns {Map<string, {prefix: string[], optional: boolean}>}
 */
function findResponseRoots(fn, body, sourceFile, responseNames) {
  /** @type {Map<string, {prefix: string[], optional: boolean}>} */
  const roots = new Map();

  for (const parameter of fn.parameters) {
    if (!ts.isIdentifier(parameter.name)) continue;
    const annotated = annotationText(parameter.type, sourceFile).includes("responses");
    if (annotated || responseNames.includes(parameter.name.text)) {
      roots.set(parameter.name.text, { prefix: [], optional: false });
    }
  }

  /** @type {import("typescript").VariableDeclaration[]} */
  const declarations = [];
  forEachDescendant(body, (node) => {
    if (ts.isVariableDeclaration(node)) declarations.push(node);
  });

  for (const declaration of declarations) {
    if (
      ts.isIdentifier(declaration.name) &&
      annotationText(declaration.type, sourceFile).includes("responses")
    ) {
      roots.set(declaration.name.text, { prefix: [], optional: false });
    }
  }

  // Alias resolution runs to a fixed point so a chain of bindings resolves, with a hard bound
  // because a cyclic declaration must not hang the extractor.
  for (let round = 0; round < 8; round += 1) {
    let added = false;
    for (const declaration of declarations) {
      if (!declaration.initializer) continue;
      const resolved = resolveAgainstRoots(declaration.initializer, roots);
      if (!resolved) continue;

      if (ts.isIdentifier(declaration.name)) {
        if (roots.has(declaration.name.text)) continue;
        roots.set(declaration.name.text, resolved);
        added = true;
        continue;
      }
      if (ts.isObjectBindingPattern(declaration.name)) {
        for (const element of declaration.name.elements) {
          if (element.dotDotDotToken || !ts.isIdentifier(element.name)) continue;
          const key = element.propertyName ? propertyKey(element.propertyName) : element.name.text;
          if (key === null || roots.has(element.name.text)) continue;
          roots.set(element.name.text, {
            prefix: [...resolved.prefix, key],
            optional: resolved.optional,
          });
          added = true;
        }
      }
    }
    if (!added) break;
  }

  return roots;
}

/**
 * @param {import("typescript").Expression} expression
 * @param {Map<string, {prefix: string[], optional: boolean}>} roots
 * @returns {{prefix: string[], optional: boolean} | null} Path this expression names, if any.
 */
function resolveAgainstRoots(expression, roots) {
  const chain = flattenAccessChain(expression);
  // A truncated chain names something *inside* an unnameable index. The binding is a real value but
  // this extractor cannot say which property it is, and an alias registered on the readable prefix
  // would attribute every later read to the wrong path.
  if (!chain || chain.truncated) return null;
  const base = roots.get(chain.root);
  if (!base) return null;
  const prefix = [...base.prefix];
  let optional = base.optional;
  for (const link of chain.links) {
    optional = optional || link.optional;
    if (link.name !== null) prefix.push(link.name);
  }
  return { prefix, optional };
}

/**
 * Record every response property a function reads, one entry per link in each chain.
 *
 * Every prefix is recorded, not only the deepest read: `response.data.items` yields `["data"]` and
 * `["data", "items"]`, because removing `data` breaks this call site just as surely as removing
 * `items`, and the entry carries the position of its own token so the verdict anchors on the exact
 * thing that broke.
 *
 * `optionalChained` is cumulative up to and including that link. `a?.b` guards the access to `b`,
 * so the entry for `["a", "b"]` is chained while the entry for `["a"]` is not — which is the
 * distinction the `became-optional` change class turns on.
 *
 * `pinned` says the read flows into a declaration that writes the type out:
 * `const s: "a" | "b" = res.status`, or the discriminant of a `switch` whose default asserts
 * `never`. This is the distinction every *widening* change class turns on — a member added to a
 * response enum, a property becoming nullable, a type changing — because widening breaks a call
 * site that named the narrow type and leaves an inferred `const` alone.
 *
 * **It is syntax, not type information.** The annotation and the `never` assertion are both tokens
 * sitting in the AST; reading them needs no checker and crosses no boundary. Without it the
 * classifier would have to abstain on the largest change class in the corpus, which would be honest
 * and useless.
 *
 * @param {import("typescript").Node} body
 * @param {import("typescript").SourceFile} sourceFile
 * @param {Map<string, {prefix: string[], optional: boolean}>} roots
 * @returns {Array<{path: string[], line: number, column: number, optionalChained: boolean, pinned: boolean}>}
 */
function collectResponseProperties(body, sourceFile, roots) {
  /** @type {Array<{path: string[], line: number, column: number, optionalChained: boolean, pinned: boolean}>} */
  const out = [];
  const seen = new Set();

  const push = (propertyPath, line, column, optionalChained, pinned) => {
    const key = `${propertyPath.join(" ")}|${line}|${column}`;
    if (seen.has(key)) return;
    seen.add(key);
    out.push({ path: [...propertyPath], line, column, optionalChained, pinned: Boolean(pinned) });
  };

  /**
   * Does this expression flow into something that names its type?
   *
   * Two shapes count, and both are the ones a real client writes when it wants the compiler to
   * hold it to a contract:
   *   `const x: Narrow = res.a;`      -- an explicit type annotation on the declaration
   *   `switch (res.a) { ... default: { const _: never = res.a; } }` -- exhaustiveness
   * Walking up the parent chain is bounded: an expression is either directly the initialiser of a
   * declaration or the discriminant of a switch, or it is neither.
   */
  const isPinned = (node) => {
    let current = node;
    // Climb out of the access chain itself so `res.a.b` is judged by what `res.a.b` flows into.
    //
    // Two ways to be inside a chain, and the first version of this only handled one of them. The
    // walker hands over the property *name* identifier (`status` in `res.status`), which is its
    // parent's `.name`, not its `.expression` -- so an `expression === current` test alone never
    // climbs at all and every read looked unpinned. Both edges have to be followed.
    while (current.parent) {
      const parent = current.parent;
      const isAccess =
        ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent);
      if (!isAccess) break;
      if (parent.expression !== current && parent.name !== current) break;
      current = parent;
    }
    const parent = current.parent;
    if (!parent) return false;
    if (ts.isVariableDeclaration(parent) && parent.initializer === current && parent.type) {
      return true;
    }
    if (ts.isSwitchStatement(parent) && parent.expression === current) {
      return switchAssertsNever(parent);
    }
    if (ts.isAsExpression(parent) || ts.isSatisfiesExpression?.(parent)) return true;
    return false;
  };

  /** A `switch` is only pinned if its default arm asserts `never` -- that is the exhaustiveness
   *  check. A `switch` with no such arm accepts a new member silently and breaks nothing. */
  const switchAssertsNever = (switchStatement) => {
    let found = false;
    forEachDescendant(switchStatement.caseBlock, (node) => {
      if (
        ts.isVariableDeclaration(node) &&
        node.type &&
        node.type.kind === ts.SyntaxKind.NeverKeyword
      ) {
        found = true;
      }
    });
    return found;
  };

  const considerChain = (node) => {
    if (isInnerLinkOfChain(node)) return;
    const chain = flattenAccessChain(node);
    if (!chain) return;
    const base = roots.get(chain.root);
    if (!base) return;

    const propertyPath = [...base.prefix];
    let optional = base.optional;
    for (const link of chain.links) {
      optional = optional || link.optional;
      if (link.name === null) continue;
      propertyPath.push(link.name);
      const { line, column } = positionOf(sourceFile, link.node);
      push(propertyPath, line, column, optional, isPinned(link.node));
    }
  };

  /**
   * Destructuring is a read with no property-access node to find, so it is walked separately.
   * `const { pspReference } = response` touches `pspReference` exactly as `response.pspReference`
   * does, and missing it would understate what the call site depends on.
   *
   * @param {import("typescript").ObjectBindingPattern} pattern
   * @param {string[]} basePath
   * @param {boolean} baseOptional
   */
  const considerBindingPattern = (pattern, basePath, baseOptional) => {
    for (const element of pattern.elements) {
      if (element.dotDotDotToken) continue;
      const key = element.propertyName
        ? propertyKey(element.propertyName)
        : ts.isIdentifier(element.name)
          ? element.name.text
          : null;
      if (key === null) continue;
      const propertyPath = [...basePath, key];
      // A destructured read never names a type for the property it pulls out.
      const { line, column } = positionOf(sourceFile, element.propertyName ?? element.name);
      push(propertyPath, line, column, baseOptional, false);
      if (ts.isObjectBindingPattern(element.name)) {
        considerBindingPattern(element.name, propertyPath, baseOptional);
      }
    }
  };

  forEachDescendant(body, (node) => {
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node)) {
      considerChain(node);
      return;
    }
    if (ts.isVariableDeclaration(node) && node.initializer && ts.isObjectBindingPattern(node.name)) {
      const resolved = resolveAgainstRoots(node.initializer, roots);
      if (resolved) considerBindingPattern(node.name, resolved.prefix, resolved.optional);
    }
  });

  return out;
}

// ------------------------------------------------------------------------------------- extraction

/**
 * Read the marker comment attached above a declaration.
 *
 * @param {import("typescript").Node} node
 * @param {string} text Full source text.
 * @returns {{callsiteId: string, operationKey: string, key: string} | null}
 */
function markerFor(node, text) {
  const ranges = ts.getLeadingCommentRanges(text, node.getFullStart()) ?? [];
  let found = null;
  for (const range of ranges) {
    const match = MARKER.exec(text.slice(range.pos, range.end));
    // Last match wins: the marker closest to the declaration is the one that names it.
    if (match) found = { callsiteId: match[1], operationKey: match[2].trim(), key: match[3] };
  }
  return found;
}

/**
 * @param {import("typescript").Node} node
 * @returns {boolean}
 */
function isExported(node) {
  return (ts.getCombinedModifierFlags(node) & ts.ModifierFlags.Export) !== 0;
}

/**
 * Pull the facts out of one call-site file.
 *
 * @param {string} absolutePath
 * @param {string} relativePath Path as reported in the output, matched to the oracle's file keys.
 * @param {string[]} responseNames
 * @param {string[]} requestNames
 * @returns {object[]}
 */
function extractFile(absolutePath, relativePath, responseNames, requestNames) {
  const text = fs.readFileSync(absolutePath, "utf8");
  const sourceFile = ts.createSourceFile(absolutePath, text, ts.ScriptTarget.ES2022, true);
  const results = [];

  /**
   * @param {import("typescript").Node} markerHost Node the marker comment sits above.
   * @param {import("typescript").SignatureDeclarationBase} fn Function carrying the parameters/body.
   */
  const handle = (markerHost, fn) => {
    const marker = markerFor(markerHost, text);
    if (!marker || !fn.body) return;

    const { line } = positionOf(sourceFile, markerHost);
    const requestProperties = [];
    for (const literal of findRequestBodyLiterals(fn.body, sourceFile, requestNames)) {
      collectRequestProperties(literal, [], sourceFile, requestProperties);
    }
    const roots = findResponseRoots(fn, fn.body, sourceFile, responseNames);
    const responseProperties = collectResponseProperties(fn.body, sourceFile, roots);

    const byPosition = (a, b) =>
      a.line - b.line || a.column - b.column || a.path.join("\u0000").localeCompare(b.path.join("\u0000"));

    results.push({
      callsiteId: marker.callsiteId,
      operationKey: marker.operationKey,
      file: relativePath,
      line,
      requestProperties: requestProperties.sort(byPosition),
      responseProperties: responseProperties.sort(byPosition),
    });
  };

  for (const statement of sourceFile.statements) {
    if (ts.isFunctionDeclaration(statement) && isExported(statement)) {
      handle(statement, statement);
      continue;
    }
    if (ts.isVariableStatement(statement) && isExported(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        const initializer = declaration.initializer ? unwrap(declaration.initializer) : undefined;
        if (
          initializer &&
          (ts.isArrowFunction(initializer) || ts.isFunctionExpression(initializer))
        ) {
          handle(statement, initializer);
        }
      }
    }
  }

  return results;
}

function main(argv) {
  const args = parseArgs(argv);
  if (!args.callsites || !args.out) {
    process.stderr.write(
      "usage: node extract-facts.mjs --callsites <dir> --out <facts.json>" +
        " [--response-param a,b] [--request-var a,b]\n",
    );
    return 2;
  }

  const callsitesDir = path.resolve(args.callsites);
  const outPath = path.resolve(args.out);
  if (!fs.existsSync(callsitesDir) || !fs.statSync(callsitesDir).isDirectory()) {
    process.stderr.write(`extract-facts: call-site directory not found: ${callsitesDir}\n`);
    return 2;
  }

  const responseNames = args["response-param"]
    ? args["response-param"].split(",").map((name) => name.trim()).filter(Boolean)
    : DEFAULT_RESPONSE_NAMES;
  const requestNames = args["request-var"]
    ? args["request-var"].split(",").map((name) => name.trim()).filter(Boolean)
    : DEFAULT_REQUEST_NAMES;

  const files = collectCallsiteFiles(callsitesDir);
  const facts = [];
  for (const file of files) {
    const relative = path.relative(callsitesDir, file).split(path.sep).join("/");
    facts.push(...extractFile(file, relative, responseNames, requestNames));
  }

  facts.sort(
    (a, b) =>
      a.callsiteId.localeCompare(b.callsiteId) ||
      a.file.localeCompare(b.file) ||
      a.line - b.line,
  );

  fs.mkdirSync(path.dirname(outPath), { recursive: true });
  fs.writeFileSync(outPath, `${JSON.stringify(facts, null, 2)}\n`, "utf8");
  process.stderr.write(
    `extract-facts: ${files.length} file(s), ${facts.length} call site(s) -> ${outPath}\n`,
  );
  return 0;
}

process.exit(main(process.argv.slice(2)));
