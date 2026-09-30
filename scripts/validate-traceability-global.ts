/**
 * Global traceability checks:
 *
 *   A. Cross-file: an item id shared by several traceability/*.yaml files
 *      must denote the same artifact (same type and name; same
 *      source/spec/actor when both declare them).
 *   B. Source of Truth: business-layer items (feature, business_rule,
 *      process_node, business_event, scenario) must exist in business/
 *      and carry exactly the Source of Truth `name`.
 *
 * See scripts/lib/traceability-global.ts. Per-file integrity stays in
 * scripts/validate-traceability.ts.
 *
 * Usage: tsx scripts/validate-traceability-global.ts [dir]
 */
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { parse } from "yaml";
import {
  BUSINESS_SOURCES,
  checkBusinessIdentity,
  checkGlobalConsistency,
  type BusinessCatalog,
  type TraceFileItems,
} from "./lib/traceability-global";

const DIR = process.argv[2] ?? "traceability";

const inputs: TraceFileItems[] = readdirSync(DIR)
  .filter((f) => f.endsWith(".yaml"))
  .sort()
  .map((f) => {
    const model = parse(readFileSync(join(DIR, f), "utf8")) as { items?: TraceFileItems["items"] };
    return { file: `${DIR}/${f}`, items: model?.items ?? [] };
  });

const result = checkGlobalConsistency(inputs);

const catalog: BusinessCatalog = {};
const parsedSources = new Map<string, Record<string, { id: string; name?: string }[]>>();
for (const [type, src] of Object.entries(BUSINESS_SOURCES)) {
  if (!parsedSources.has(src.file)) parsedSources.set(src.file, parse(readFileSync(src.file, "utf8")));
  const list = parsedSources.get(src.file)?.[src.listKey] ?? [];
  catalog[type] = new Map(
    list
      .filter((e) => !src.idPrefix || e.id.startsWith(src.idPrefix))
      .map((e) => [e.id, e.name ?? ""] as [string, string]),
  );
}
const business = checkBusinessIdentity(inputs, catalog);

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

for (const i of business.issues) {
  if (i.kind === "missing") {
    console.error("ERROR: traceability business identity not found\n");
    console.error(`ID: ${i.id}`);
    console.error(`${i.file}\n`);
    console.error(`Expected source:\n${i.expectedSource}\n`);
  } else {
    console.error("ERROR: traceability differs from business source of truth\n");
    console.error(`ID: ${i.id} (${i.file})\n`);
    console.error(`traceability:\n  ${i.traceabilityName}\n`);
    console.error(`business source:\n  ${i.businessName}\n`);
  }
}

if (result.collisions.length > 0) {
  console.error(`FAIL: ${result.collisions.length} conflicting ID(s) across ${result.files} files.`);
}
if (business.issues.length > 0) {
  console.error(
    `FAIL: ${business.missing} missing business ID(s), ${business.nameMismatches} name mismatch(es) vs source of truth.`,
  );
}
if (result.collisions.length > 0 || business.issues.length > 0) process.exit(1);

console.log(`OK: global traceability IDs are consistent across ${result.files} files.`);
console.log(`  unique IDs:      ${result.uniqueIds}`);
console.log(`  shared IDs:      ${result.sharedIds}`);
console.log(`  conflicting IDs: 0`);
console.log("OK: business identities match source of truth.");
console.log(`  checked business identities: ${business.checked}`);
console.log(`  missing IDs: 0`);
console.log(`  name mismatches: 0`);
