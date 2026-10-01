/**
 * Runs scripts/validate-traceability.ts on EVERY traceability/*.yaml, so a
 * new Scenario's file is validated without listing it by hand.
 *
 * Usage: tsx scripts/validate-traceability-files.ts [dir]
 */
import { spawnSync } from "node:child_process";
import { readdirSync } from "node:fs";

const DIR = process.argv[2] ?? "traceability";

const files = readdirSync(DIR)
  .filter((f) => f.endsWith(".yaml"))
  .sort();

if (files.length === 0) {
  console.error(`ERROR: no hay archivos de trazabilidad en ${DIR}/`);
  process.exit(1);
}

let failed = 0;
for (const f of files) {
  const result = spawnSync("npx", ["tsx", "scripts/validate-traceability.ts", `${DIR}/${f}`], {
    stdio: "inherit",
    shell: true,
  });
  if (result.status !== 0) failed++;
}

if (failed > 0) {
  console.error(`FAIL: ${failed} de ${files.length} archivos de trazabilidad no validan.`);
  process.exit(1);
}
console.log(`OK: ${files.length} archivos de trazabilidad validan individualmente.`);
