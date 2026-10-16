/**
 * Validates the machine-readable traceability graph
 * (traceability/hp-rep-001.yaml), built as **items + links** per the
 * design decision recorded in traceability/README.md.
 *
 * Why TypeScript and not Python: this repository already validates every
 * other business artifact with tsx scripts under `scripts/` (see
 * validate-process.ts, validate-features.ts, validate-references.ts,
 * validate-scenarios.ts), already depends on `yaml` and `tsx` in
 * package.json, and exposes them all through `npm run validate:*`.
 * Keeping the traceability validator in the same place and the same
 * language means one validation surface for the whole repository, zero
 * new dependencies and zero new runtimes. The Python side of the repo is
 * the backend application itself, whose test harness (pytest) verifies
 * behaviour, not artifact integrity - a different concern.
 *
 * Checks performed:
 *
 *   1. Every item id is unique.
 *   2. Every link endpoint (`from` / `to`) resolves to a declared item;
 *      no broken references. Relationships must come from the declared
 *      vocabulary.
 *   3. Every User Story belongs to a Feature.
 *   4. Every System Action realizes at least one User Story (unless it
 *      explicitly declares `pending_formalization: <reason>`: an
 *      implemented capability whose User Story is not yet formally
 *      defined in business/; it is reported as a warning, never hidden).
 *   5. Every Functional Requirement derives from at least one System
 *      Action.
 *   6. Every Technical Requirement satisfies at least one Functional
 *      Requirement (unless explicitly flagged `cross_cutting: true`).
 *   7. Every Code artifact is linked to a Task and/or a Technical
 *      Requirement.
 *   8. Every Internal Test is related to a Code artifact, a Functional
 *      Requirement or a Technical Requirement.
 *   9. Every Task with status DONE implements at least one Technical
 *      Requirement. Tasks with status NOT_IMPLEMENTED are allowed to be
 *      unlinked on purpose: they are the explicit record of what the
 *      Business Process foresees and the implemented slice does not
 *      cover.
 *  10. UAT items are allowed - and expected - to be PENDING. What is NOT
 *      allowed is an approved UAT with no evidence of a formal
 *      acceptance round, so any non-PENDING UAT is reported.
 *  11. Coverage hygiene: no Feature may claim to be implemented. A
 *      Feature carries `feature_status` (the V1.3 Feature) and
 *      `implemented_slice_status` (the HP-REP-001 slice) separately.
 *
 * It also prints a coverage summary per level. It never mutates the
 * graph and never touches production code.
 *
 * The traceability file is parameterizable via an optional positional
 * CLI arg (`tsx scripts/validate-traceability.ts [file]`), the same
 * convention as the other validators.
 */
import { readFileSync } from "node:fs";
import { parse } from "yaml";

const DEFAULT_TRACE_FILE = "traceability/hp-rep-001.yaml";
const TRACE_FILE = process.argv[2] ?? DEFAULT_TRACE_FILE;

type Item = {
  id: string;
  type: string;
  name?: string;
  status?: string;
  cross_cutting?: boolean;
  pending_formalization?: string;
  feature_status?: string;
  implemented_slice_status?: string;
  [key: string]: unknown;
};

type Link = {
  from: string;
  to: string;
  relationship: string;
  note?: string;
};

type TraceModel = {
  meta?: { relationship_vocabulary?: Record<string, string> };
  items?: Item[];
  links?: Link[];
};

const errors: string[] = [];
const warnings: string[] = [];

function fail(message: string): void {
  errors.push(message);
}

function warn(message: string): void {
  warnings.push(message);
}

function loadTrace(file: string): TraceModel {
  let raw: string;
  try {
    raw = readFileSync(file, "utf8");
  } catch {
    console.error(`ERROR: no se pudo leer ${file}`);
    process.exit(1);
  }
  try {
    return parse(raw) as TraceModel;
  } catch (error) {
    console.error(`ERROR: ${file} no es YAML valido: ${String(error)}`);
    process.exit(1);
  }
}

const model = loadTrace(TRACE_FILE);
const items: Item[] = model.items ?? [];
const links: Link[] = model.links ?? [];

if (items.length === 0) {
  fail("El archivo no declara ningun item.");
}
if (links.length === 0) {
  fail("El archivo no declara ningun link.");
}

// --- 1. IDs unicos ------------------------------------------------- //

const byId = new Map<string, Item>();
const duplicates: string[] = [];
for (const item of items) {
  if (!item || typeof item.id !== "string" || item.id.length === 0) {
    fail(`Item sin id valido: ${JSON.stringify(item)}`);
    continue;
  }
  if (!item.type) {
    fail(`Item ${item.id} no declara type.`);
  }
  if (!item.name && item.name !== "") {
    fail(`Item ${item.id} no declara name.`);
  }
  if (byId.has(item.id)) {
    duplicates.push(item.id);
  } else {
    byId.set(item.id, item);
  }
}
for (const id of [...new Set(duplicates)].sort()) {
  fail(`ID duplicado: ${id}`);
}

// --- 2. Links sin referencias rotas -------------------------------- //

const vocabulary = new Set(
  Object.keys(model.meta?.relationship_vocabulary ?? {}),
);

type Edge = { to: string; relationship: string };
const outgoing = new Map<string, Edge[]>();
const incoming = new Map<string, Edge[]>();

for (const link of links) {
  if (!link || !link.from || !link.to || !link.relationship) {
    fail(`Link incompleto: ${JSON.stringify(link)}`);
    continue;
  }
  if (!byId.has(link.from)) {
    fail(
      `Referencia rota: el link ${link.from} -${link.relationship}-> ` +
        `${link.to} apunta a un origen inexistente (${link.from}).`,
    );
  }
  if (!byId.has(link.to)) {
    fail(
      `Referencia rota: el link ${link.from} -${link.relationship}-> ` +
        `${link.to} apunta a un destino inexistente (${link.to}).`,
    );
  }
  if (vocabulary.size > 0 && !vocabulary.has(link.relationship)) {
    fail(
      `Relationship fuera del vocabulario declarado: ` +
        `"${link.relationship}" (${link.from} -> ${link.to}).`,
    );
  }
  if (!outgoing.has(link.from)) outgoing.set(link.from, []);
  outgoing.get(link.from)!.push({ to: link.to, relationship: link.relationship });
  if (!incoming.has(link.to)) incoming.set(link.to, []);
  incoming.get(link.to)!.push({ to: link.from, relationship: link.relationship });
}

function itemsOfType(type: string): Item[] {
  return items.filter((item) => item.type === type);
}

function hasOutgoing(id: string, relationship: string, targetType: string): boolean {
  return (outgoing.get(id) ?? []).some(
    (edge) =>
      edge.relationship === relationship && byId.get(edge.to)?.type === targetType,
  );
}

function hasOutgoingAnyType(id: string, relationship: string, targetTypes: string[]): boolean {
  return (outgoing.get(id) ?? []).some(
    (edge) =>
      edge.relationship === relationship &&
      targetTypes.includes(byId.get(edge.to)?.type ?? ""),
  );
}

// --- 3..6. Cadena funcional ---------------------------------------- //

for (const us of itemsOfType("user_story")) {
  if (!hasOutgoing(us.id, "belongs_to", "feature")) {
    fail(`${us.id} no pertenece a ninguna Feature.`);
  }
}

for (const acc of itemsOfType("system_action")) {
  if (hasOutgoing(acc.id, "realizes", "user_story")) continue;
  const pendiente = acc.pending_formalization;
  if (typeof pendiente === "string" && pendiente.trim() !== "") {
    warn(
      `${acc.id} no realiza ninguna User Story: formalizacion pendiente ` +
        `(${pendiente.trim()})`,
    );
    continue;
  }
  fail(`${acc.id} no realiza ninguna User Story.`);
}

for (const fr of itemsOfType("functional_requirement")) {
  if (!hasOutgoing(fr.id, "derives_from", "system_action")) {
    fail(`${fr.id} no deriva de ninguna System Action.`);
  }
}

for (const tr of itemsOfType("technical_requirement")) {
  if (hasOutgoing(tr.id, "satisfies", "functional_requirement")) continue;
  if (tr.cross_cutting === true) {
    warn(
      `${tr.id} no satisface ningun Functional Requirement, pero esta ` +
        `declarado cross_cutting: true (estandar transversal).`,
    );
    continue;
  }
  fail(`${tr.id} no satisface ningun Functional Requirement.`);
}

// --- 7. Code -> Task / Technical Requirement ----------------------- //

for (const code of itemsOfType("code_artifact")) {
  const linkedToTask = hasOutgoing(code.id, "produced_by", "task");
  const linkedToTr = hasOutgoing(code.id, "implements", "technical_requirement");
  if (!linkedToTask && !linkedToTr) {
    fail(`${code.id} no esta vinculado a ninguna Task ni Technical Requirement.`);
  }
}

// --- 8. Internal Test -> Code / FR / TR ---------------------------- //

for (const test of itemsOfType("internal_test")) {
  const exercisesCode = hasOutgoing(test.id, "exercises", "code_artifact");
  const verifiesReq = hasOutgoingAnyType(test.id, "verifies", [
    "functional_requirement",
    "technical_requirement",
  ]);
  if (!exercisesCode && !verifiesReq) {
    fail(
      `${test.id} no esta relacionado con ningun Code artifact, ` +
        `Functional Requirement ni Technical Requirement.`,
    );
  }
  if (!test.source) {
    fail(`${test.id} no declara source (archivo::funcion).`);
  }
}

// --- 9. Tasks DONE -> Technical Requirement ------------------------ //

for (const task of itemsOfType("task")) {
  if (task.status !== "DONE") continue;
  if (!hasOutgoing(task.id, "implements", "technical_requirement")) {
    fail(
      `${task.id} esta marcada DONE pero no implementa ningun Technical ` +
        `Requirement. Una Task solo se marca DONE con evidencia real.`,
    );
  }
}

// --- 10. UAT ------------------------------------------------------- //

const uats = itemsOfType("uat");
for (const uat of uats) {
  if (!hasOutgoingAnyType(uat.id, "accepts", ["user_story", "functional_requirement"])) {
    fail(`${uat.id} no acepta ninguna User Story ni Functional Requirement.`);
  }
  // PENDING es el estado esperado en esta baseline: no hubo UAT formal.
  if (uat.status !== "PENDING") {
    warn(
      `${uat.id} tiene status "${uat.status}" en lugar de PENDING. ` +
        `Un UAT solo deja de estar PENDING con una ronda de aceptacion ` +
        `formal de negocio; los tests internos NO son evidencia de UAT.`,
    );
  }
}

// --- 11. Higiene de cobertura Feature vs. slice -------------------- //

for (const feature of itemsOfType("feature")) {
  if (feature.feature_status === undefined) {
    fail(`${feature.id} no declara feature_status.`);
  }
  if (feature.implemented_slice_status === undefined) {
    fail(`${feature.id} no declara implemented_slice_status.`);
  }
  if (feature.feature_status === "IMPLEMENTED" || feature.status === "IMPLEMENTED") {
    fail(
      `${feature.id} se declara IMPLEMENTED. Ninguna Feature V1.3 esta ` +
        `implementada: lo implementado es el slice de HP-REP-001. Use ` +
        `feature_status: draft + implemented_slice_status: IMPLEMENTED.`,
    );
  }
  if (
    feature.implemented_slice_status === "IMPLEMENTED" &&
    !feature.implemented_scenario
  ) {
    fail(
      `${feature.id} declara un slice IMPLEMENTED sin indicar ` +
        `implemented_scenario.`,
    );
  }
}

// --- Resumen ------------------------------------------------------- //

console.log("=== Validacion de trazabilidad ===");
console.log("");
console.log(`Archivo: ${TRACE_FILE}`);
console.log(`  Items: ${items.length}`);
console.log(`  Links: ${links.length}`);
console.log("");

const typeOrder = [
  "business_domain",
  "business_process",
  "scenario",
  "feature",
  "business_event",
  "process_node",
  "business_rule",
  "user_story",
  "system_action",
  "functional_requirement",
  "technical_requirement",
  "data_model_artifact",
  "task",
  "code_artifact",
  "internal_test",
  "uat",
];
console.log("  Items por nivel:");
for (const type of typeOrder) {
  const count = itemsOfType(type).length;
  if (count > 0) {
    console.log(`    ${type.padEnd(24)} ${String(count).padStart(4)}`);
  }
}
const unknownTypes = [...new Set(items.map((i) => i.type))].filter(
  (t) => !typeOrder.includes(t),
);
for (const type of unknownTypes) {
  console.log(`    ${String(type).padEnd(24)} ${String(itemsOfType(type).length).padStart(4)}  (tipo no listado)`);
}
console.log("");

const relCounts = new Map<string, number>();
for (const link of links) {
  relCounts.set(link.relationship, (relCounts.get(link.relationship) ?? 0) + 1);
}
console.log("  Links por relationship:");
for (const [rel, count] of [...relCounts.entries()].sort()) {
  console.log(`    ${rel.padEnd(24)} ${String(count).padStart(4)}`);
}
console.log("");

const tasks = itemsOfType("task");
const done = tasks.filter((t) => t.status === "DONE").length;
console.log("  Cobertura del slice implementado (HP-REP-001):");
console.log(`    Tasks DONE (codigo + test):        ${done} / ${tasks.length}`);
console.log(`    Tasks NOT_IMPLEMENTED (gaps):      ${tasks.length - done}`);
const pending = uats.filter((u) => u.status === "PENDING").length;
console.log(`    UAT PENDING:                       ${pending} / ${uats.length}`);
const features = itemsOfType("feature");
const sliceImplemented = features.filter(
  (f) => f.implemented_slice_status === "IMPLEMENTED",
).length;
console.log(
  `    Features con slice IMPLEMENTED:    ${sliceImplemented} / ${features.length}` +
    `  (ninguna Feature esta implementada por completo)`,
);
console.log("");

if (warnings.length > 0) {
  console.log("  Advertencias:");
  for (const message of warnings) {
    console.log(`    - ${message}`);
  }
  console.log("");
}

if (errors.length > 0) {
  console.error(`ERROR: la trazabilidad tiene ${errors.length} problema(s):`);
  for (const message of errors) {
    console.error(`  - ${message}`);
  }
  process.exit(1);
}

console.log(`OK: ${TRACE_FILE} es un grafo de trazabilidad integro.`);
