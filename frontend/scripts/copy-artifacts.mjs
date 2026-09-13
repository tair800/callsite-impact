/**
 * Copy the committed artifacts next to the app, for a deployment whose build root is `frontend/`.
 *
 * Running the console locally needs none of this: `lib/source.ts` falls back to `../artifacts`,
 * which is the repository's own committed copy. This script exists only because a platform that
 * builds and traces from inside `frontend/` will not include a file above that directory in the
 * deployed bundle.
 *
 * It is deliberately not a failure when there is nothing to copy. A build in a checkout where the
 * measurement has not been run should still produce a console — one that shows the empty state and
 * tells the reader what to run. Failing the build instead would replace an explanation with a red
 * log line.
 */
import { promises as fs } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const frontend = path.resolve(here, "..");
const source = path.resolve(frontend, "..", "artifacts");
const destination = path.join(frontend, "artifacts");

// `holdout.json` is optional -- a checkout that has not run the confirmatory slice still
// builds, and the console renders the "not measured" state rather than implying a number it
// does not have. Omitting it here would produce exactly that false impression on a deployment
// where the slice HAS been measured, which is the direction that matters.
const FILES = ["evaluation.json", "findings.json", "holdout.json"];

async function main() {
  let copied = 0;
  for (const name of FILES) {
    const from = path.join(source, name);
    try {
      await fs.access(from);
    } catch {
      console.log(`artifacts: ${name} not present in ${source}; skipping`);
      continue;
    }
    await fs.mkdir(destination, { recursive: true });
    await fs.copyFile(from, path.join(destination, name));
    copied += 1;
    console.log(`artifacts: copied ${name}`);
  }
  if (copied === 0) {
    console.log(
      "artifacts: nothing copied. The console will render its empty state and ask for " +
        "`make corpus && make killtest`.",
    );
  }
}

await main();
