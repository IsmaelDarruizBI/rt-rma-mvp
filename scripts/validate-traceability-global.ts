/**
 * Cross-file traceability check: an item id shared by several
 * traceability/*.yaml files must denote the same artifact (same type and
 * name; same source/spec/actor when both declare them). See
 * scripts/lib/traceability-global.ts. Per-file integrity stays in
 * scripts/validate-traceability.ts.
 *
 * Usage: tsx scripts/validate-traceability-global.ts [dir]
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import { checkGlobalConsistency, type TraceFileItems } from "./lib/traceability-global";

const DIR = process.argv[2] ?? "traceability";

const inputs: TraceFileItems[] = readdirSync(DIR)
  .filter((f) => f.endsWith(".yaml"))
  .sort()
  .map((f) => {
    const model = parse(readFileSync(join(DIR, f), "utf8")) as { items?: TraceFileItems["items"] };
    return { file: `${DIR}/${f}`, items: model?.items ?? [] };
  });

const result = checkGlobalConsistency(inputs);

if (result.collisions.length > 0) {
  for (const c of result.collisions) {
    console.error("ERROR: global traceability ID collision\n");
    console.error(`ID: ${c.id}\n`);
    for (const o of c.occurrences) {
      console.error(o.file);
      console.error(`  type: ${o.item.type}`);
      console.error(`  name: ${o.item.name}`);
      for (const f of o.differing) {
        if (f !== "type" && f !== "name") console.error(`  ${f}: ${String(o.item[f])}`);
      }
    }
    console.error("\nSame ID represents different artifacts.\n");
  }
  console.error(`FAIL: ${result.collisions.length} conflicting ID(s) across ${result.files} files.`);
  process.exit(1);
}

console.log(`OK: global traceability IDs are consistent across ${result.files} files.`);
console.log(`  unique IDs:      ${result.uniqueIds}`);
console.log(`  shared IDs:      ${result.sharedIds}`);
console.log(`  conflicting IDs: 0`);
