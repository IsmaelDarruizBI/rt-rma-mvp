/**
 * Keeps traceability/discrepancias-baseline-v1.4.md honest after each
 * synchronization of business/ (DC02): the differences between the baseline
 * in force and the product are registered, never hidden.
 *
 * Checks:
 *   1. Every decision of business/decisions/decision-log-v1.4.yaml whose
 *      implementation is PARCIAL, NO_IMPLEMENTADO or CONTRARIO has a row in
 *      the document (a line that starts with "| <id> |").
 *   2. Every UAT incorporation that is not CONFIRMADO is mentioned.
 *   3. The document cites the source commit of business/FUNCTIONAL_SOURCE.json,
 *      so a new synchronization forces a review of the list.
 *
 * Run: npm run validate:discrepancies
 */
import { readFileSync } from "node:fs";
import { loadYaml } from "./lib/process-model";

const LOG_FILE = "business/decisions/decision-log-v1.4.yaml";
const MANIFEST_FILE = "business/FUNCTIONAL_SOURCE.json";
const DOC_FILE = "traceability/discrepancias-baseline-v1.4.md";
const GAP_STATUS = ["PARCIAL", "NO_IMPLEMENTADO", "CONTRARIO"];

interface DecisionLog {
  decisions: { id: string; implementation: { status: string } }[];
  uat_items: { id: string; status: string }[];
}

const log = loadYaml<DecisionLog>(LOG_FILE);
const manifest = JSON.parse(readFileSync(MANIFEST_FILE, "utf8")) as { source_commit: string };
const doc = readFileSync(DOC_FILE, "utf8");
const rows = new Set(doc.split(/\r?\n/).map((line) => /^\| ([A-Z0-9-]+) \|/.exec(line)?.[1]).filter(Boolean));

const errors: string[] = [];
const gaps = log.decisions.filter((d) => GAP_STATUS.includes(d.implementation.status));
for (const d of gaps) {
  if (!rows.has(d.id)) errors.push(`${d.id} (${d.implementation.status}) no tiene fila en ${DOC_FILE}`);
}
const unconfirmed = log.uat_items.filter((u) => u.status !== "CONFIRMADO");
for (const u of unconfirmed) {
  if (!doc.includes(u.id)) errors.push(`${u.id} (${u.status}) no se menciona en ${DOC_FILE}`);
}
if (!doc.includes(manifest.source_commit)) {
  errors.push(`${DOC_FILE} no cita el commit de origen ${manifest.source_commit}: revisar la lista tras la sincronizacion`);
}

if (errors.length > 0) {
  console.error("ERRORES:");
  for (const error of errors) console.error(`  - ${error}`);
  console.error(`\nFAILED: ${errors.length} discrepancia(s) sin registrar.`);
  process.exit(1);
}
console.log(
  `OK: ${DOC_FILE} registra las ${gaps.length} decisiones con implementacion pendiente y las ${unconfirmed.length} incorporaciones de UAT sin confirmar de ${manifest.source_commit.slice(0, 7)}.`,
);
