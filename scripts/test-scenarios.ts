/**
 * Dependency-free tests for the Scenario layer (Happy Paths today, Variant
 * scaffolding tomorrow): the real HP-REP-001/HP-REP-002 in
 * business/scenarios/repair-management-scenarios-v1.3.yaml, plus NEGATIVE
 * cases built by mutating a deep clone of a real Happy Path and asserting
 * validateScenario() reports the expected error (so the validator is proven
 * to actually detect these defects, not just to pass on good data).
 *
 * Run with `tsx scripts/test-scenarios.ts`. Same style as
 * test-feature-scenario-mapping.ts: node:assert/strict, no framework.
 */
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Ajv from "ajv";
import { legacyDetailStateUses, renameLegacyDetailStates } from "./lib/detail-states";
import { loadYaml, type ProcessModel } from "./lib/process-model";
import type { FeatureModel } from "./lib/feature-model";
import { deriveScenarioFeatures } from "./lib/feature-scenario-mapping";
import { isProcessEdgeStep, type Scenario, type ScenarioModel } from "./lib/scenario-model";
import { findDuplicateIds, validateScenario } from "./validate-scenarios";

// Revision under test: `tsx scripts/test-scenarios.ts v1.4` (defaults to
// v1.3, so the existing command is unchanged).
const REVISION = process.argv[2] ?? "v1.3";
// V1.4 (AUD-V14-001): todo fin pasa por la verificacion de saldo a favor (PROC-REP-268); V1.3 conserva 270 -> EVT-REP-999
const V14 = REVISION === "v1.4";
const withGate = (ids: string[]): string[] => (V14 ? [...ids.slice(0, -1), "PROC-REP-268", ids[ids.length - 1]] : ids);
const PROCESS_FILE = `business/processes/repair-management-${REVISION}.yaml`;
const FEATURES_FILE = `business/features/repair-management-features-${REVISION}.yaml`;
const SCENARIOS_FILE = `business/scenarios/repair-management-scenarios-${REVISION}.yaml`;
const SCHEMA_FILE = "business/schemas/scenario.schema.json";

const processModel = loadYaml<ProcessModel>(PROCESS_FILE);
const featuresModel = loadYaml<FeatureModel>(FEATURES_FILE);
const scenariosModel = loadYaml<ScenarioModel>(SCENARIOS_FILE);
const featureIds = new Set(featuresModel.features.map((feature) => feature.id));
const rulesModel = loadYaml<{ rules: { id: string; name: string; description?: string }[] }>(
  `business/rules/business-rules-${REVISION}.yaml`
);
const nodeById = new Map(processModel.nodes.map((node) => [node.id, node]));
const scenariosById = new Map(scenariosModel.scenarios.map((scenario) => [scenario.id, scenario]));

function real(id: string): Scenario {
  const scenario = scenariosById.get(id);
  assert.ok(scenario, `scenario ${id} must exist`);
  return scenario;
}

function clone(id: string): Scenario {
  return structuredClone(real(id));
}

function errorsOf(scenario: Scenario): string[] {
  const map = new Map(scenariosById);
  map.set(scenario.id, scenario);
  return validateScenario(scenario, processModel, featureIds, map);
}

function traversedNodes(scenario: Scenario): Set<string> {
  const set = new Set<string>();
  for (const step of scenario.steps) {
    if (isProcessEdgeStep(step)) {
      set.add(step.from);
      set.add(step.to);
    }
  }
  return set;
}

let failures = 0;
function check(name: string, fn: () => void): void {
  try {
    fn();
    console.log(`  OK   ${name}`);
  } catch (error) {
    failures++;
    console.error(`  FAIL ${name}`);
    console.error(`       ${error instanceof Error ? error.message : String(error)}`);
  }
}

function expectError(scenario: Scenario, fragment: string): void {
  const errors = errorsOf(scenario);
  assert.ok(
    errors.some((error) => error.includes(fragment)),
    `expected an error containing "${fragment}", got: ${JSON.stringify(errors)}`
  );
}

console.log("Happy Paths reales\n");

check("HP-REP-001, HP-REP-002 y HP-REP-003 existen, IDs unicos", () => {
  assert.deepEqual(findDuplicateIds(scenariosModel.scenarios), []);
  assert.ok(scenariosById.has("HP-REP-001"));
  assert.ok(scenariosById.has("HP-REP-002"));
  assert.ok(scenariosById.has("HP-REP-003"));
});

check("los tres Happy Paths validan sin errores", () => {
  assert.deepEqual(errorsOf(real("HP-REP-001")), []);
  assert.deepEqual(errorsOf(real("HP-REP-002")), []);
  assert.deepEqual(errorsOf(real("HP-REP-003")), []);
});

/** Ordered list of edge steps' "to" nodes, for order assertions (start node prepended). */
function orderOf(scenario: Scenario): string[] {
  const edges = scenario.steps.filter(isProcessEdgeStep);
  return [edges[0].from, ...edges.map((step) => step.to)];
}

check("HP-REP-002 sigue siendo un camino valido, RT_INTERNO, de inicio a fin", () => {
  const scenario = real("HP-REP-002");
  assert.deepEqual(errorsOf(scenario), []);
  const order = orderOf(scenario);
  assert.equal(order[0], "EVT-REP-001");
  assert.equal(order[order.length - 1], "EVT-REP-999");
  assert.ok(order.includes("PROC-REP-020"), "recibe contexto del equipo RT (PROC-REP-020)");
  assert.ok(!order.includes("PROC-REP-030"), "no registra cliente");
});

check("HP-REP-002 no recorre pago, validacion de saldo, comprobante final ni notificacion comercial a cliente", () => {
  const nodes = traversedNodes(real("HP-REP-002"));
  for (const commercial of ["PROC-REP-265", "PROC-REP-266", "PROC-REP-280", "PROC-REP-260", "PROC-REP-060"]) {
    assert.ok(!nodes.has(commercial), `${commercial} no debe ser atravesado`);
  }
  assert.ok(!real("HP-REP-002").steps.some((step) => step.kind === "FUNCTIONAL_ACTION"), "sin acciones funcionales de pago");
});

check("HP-REP-002 recorre PROC-REP-290 y luego la entrega/devolucion PROC-REP-270", () => {
  const order = orderOf(real("HP-REP-002"));
  assert.ok(order.includes("PROC-REP-290"), "recorre PROC-REP-290");
  assert.ok(order.includes("PROC-REP-270"), "recorre PROC-REP-270 (entrega/devolucion a Gestion RT)");
});

check("orden: REPARACION_LISTA(240) -> 250 -> 290 (informar) -> 270 (entrega/devolucion) -> [V1.4: 268 verificacion de saldo a favor] -> FIN", () => {
  const order = orderOf(real("HP-REP-002"));
  const at = (id: string): number => order.indexOf(id);
  assert.ok(at("PROC-REP-240") < at("PROC-REP-250"));
  assert.ok(at("PROC-REP-250") < at("PROC-REP-290"));
  assert.ok(at("PROC-REP-290") < at("PROC-REP-270"), "el resultado se informa ANTES de registrar la devolucion");
  assert.ok(at("PROC-REP-270") < at("EVT-REP-999"), "la entrega/devolucion ocurre antes del cierre/fin");
  if (V14) assert.ok(at("PROC-REP-270") < at("PROC-REP-268") && at("PROC-REP-268") < at("EVT-REP-999"), "V1.4: la devolucion ocurre antes de la verificacion de saldo a favor y del fin");
  assert.deepEqual(order.slice(V14 ? -6 : -5), withGate(["PROC-REP-240", "PROC-REP-250", "PROC-REP-290", "PROC-REP-270", "EVT-REP-999"]));
});

check("PROC-REP-270 no esta en skipped_nodes de HP-REP-002 (es entrega/devolucion a Gestion RT)", () => {
  assert.ok(!(real("HP-REP-002").skipped_nodes ?? []).some((skipped) => skipped.node === "PROC-REP-270"));
});

check("HP-REP-001 no cambia: no recorre PROC-REP-290 y entrega a cliente via 265 -> 280 -> 270", () => {
  const order = orderOf(real("HP-REP-001"));
  assert.ok(!order.includes("PROC-REP-290"));
  assert.ok(order.lastIndexOf("PROC-REP-265") < order.indexOf("PROC-REP-280"));
  assert.ok(order.indexOf("PROC-REP-280") < order.indexOf("PROC-REP-270"));
});

check("terminal_state de HP-REP-002 sigue PENDIENTE_DE_DEFINIR (sin estado inventado)", () => {
  const terminal = (real("HP-REP-002").expected).find((fact) => fact.key === "terminal_state");
  assert.equal(terminal?.value, "PENDIENTE_DE_DEFINIR");
});

check("todo skipped_nodes de HP-REP-002 esta realmente omitido y tiene motivo", () => {
  const scenario = real("HP-REP-002");
  const nodes = traversedNodes(scenario);
  assert.ok((scenario.skipped_nodes ?? []).length > 0);
  for (const skipped of scenario.skipped_nodes ?? []) {
    assert.ok(!nodes.has(skipped.node), `${skipped.node} esta en skipped_nodes pero se atraviesa`);
    assert.ok(skipped.reason.trim().length > 0, `${skipped.node} sin motivo`);
  }
});

check("HP-REP-001 y HP-REP-002 son caminos distintos (no se duplica un HP por origen)", () => {
  const a = traversedNodes(real("HP-REP-001"));
  const b = traversedNodes(real("HP-REP-002"));
  assert.ok(a.has("PROC-REP-030") && !b.has("PROC-REP-030"));
  assert.ok(b.has("PROC-REP-290") && !a.has("PROC-REP-290"));
});

check("active_features HP-REP-002 = FEAT-REP-001..008, sin FEAT-REP-009", () => {
  const { activeFeatureIds } = deriveScenarioFeatures(featuresModel, real("HP-REP-002"));
  assert.deepEqual(activeFeatureIds, [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `FEAT-REP-00${n}`));
});

check("FEAT-REP-007 permanece activa en HP-REP-002 (con comportamiento distinto al de HP-REP-001)", () => {
  const rt = deriveScenarioFeatures(featuresModel, real("HP-REP-002"));
  const ext = deriveScenarioFeatures(featuresModel, real("HP-REP-001"));
  assert.ok(rt.activeFeatureIds.includes("FEAT-REP-007"), "FEAT-REP-007 debe estar activa en HP-REP-002");
  assert.ok(ext.activeFeatureIds.includes("FEAT-REP-007"), "FEAT-REP-007 debe estar activa en HP-REP-001");
  // Same Feature, different behavior: only HP-REP-001 traverses its own payment/balance nodes.
  const feat7 = featuresModel.features.find((f) => f.id === "FEAT-REP-007");
  assert.ok(feat7);
  const ownPayment = ["PROC-REP-265", "PROC-REP-266"];
  assert.ok(ownPayment.every((n) => feat7.process_nodes.includes(n)));
  assert.ok(ownPayment.every((n) => traversedNodes(real("HP-REP-001")).has(n)));
  assert.ok(ownPayment.every((n) => !traversedNodes(real("HP-REP-002")).has(n)));
});

check("la derivacion explica POR QUE cada Feature esta activa (razones), sin implicar una unica causa", () => {
  const { activationReasons, activeFeatureIds } = deriveScenarioFeatures(featuresModel, real("HP-REP-002"));
  for (const featureId of activeFeatureIds) {
    assert.ok((activationReasons[featureId] ?? []).length > 0, `${featureId} sin razon de activacion`);
  }
  assert.ok(activationReasons["FEAT-REP-007"].some((reason) => reason.includes("PROC-REP-070")));
  assert.ok(activationReasons["FEAT-REP-008"].some((reason) => reason.includes("PROC-REP-270")));
  assert.ok(activationReasons["FEAT-REP-008"].some((reason) => reason.includes("PROC-REP-290")));
});

check("ningun nodo esta a la vez en steps[] y en skipped_nodes (HP-REP-001 y HP-REP-002)", () => {
  for (const id of ["HP-REP-001", "HP-REP-002", "HP-REP-003"]) {
    const nodes = traversedNodes(real(id));
    for (const skipped of real(id).skipped_nodes ?? []) {
      assert.ok(!nodes.has(skipped.node), `${id}: ${skipped.node} en steps y skipped_nodes`);
    }
  }
});



console.log("\nHP-REP-003 - Garantia de reparacion RMA\n");

const factOf = (scenario: Scenario, key: string): unknown => scenario.facts.find((fact) => fact.key === key)?.value;
const expectedOf = (scenario: Scenario, key: string): unknown => scenario.expected.find((fact) => fact.key === key)?.value;
const desc = (nodeId: string): string => (nodeById.get(nodeId)?.description ?? "").replace(/\s+/g, " ");
const ruleText = (ruleId: string): string =>
  (rulesModel.rules.find((rule) => rule.id === ruleId)?.description ?? "").replace(/\s+/g, " ");

check("1) existe HP-REP-003 (HAPPY_PATH/E2E) y valida sin errores", () => {
  const scenario = real("HP-REP-003");
  assert.equal(scenario.type, "HAPPY_PATH");
  assert.equal(scenario.scope, "E2E");
  assert.deepEqual(errorsOf(scenario), []);
});

check("2) el trigger es garantia sobre una reparacion anterior (EVT-REP-002, no EVT-REP-001)", () => {
  const order = orderOf(real("HP-REP-003"));
  assert.equal(order[0], "EVT-REP-002");
  assert.ok(!order.includes("EVT-REP-001"));
  assert.match(nodeById.get("EVT-REP-002")?.name ?? "", /garantia/i);
  assert.match(desc("EVT-REP-002"), /Iniciar garantia RMA/);
  // entry point: no incoming edges; converges into PROC-REP-035
  assert.ok(!processModel.edges.some((edge) => edge.to === "EVT-REP-002"));
  assert.ok(processModel.edges.some((edge) => edge.from === "EVT-REP-002" && edge.to === "PROC-REP-035"));
});

check("3) se identifica la Orden anterior (PROC-REP-035, Orden origen finalizada como input)", () => {
  const node = nodeById.get("PROC-REP-035");
  assert.ok(node);
  assert.ok(orderOf(real("HP-REP-003")).includes("PROC-REP-035"));
  assert.ok((node.inputs ?? []).some((input) => /Orden de Reparacion origen/.test(input)));
  assert.ok((node.outputs ?? []).some((output) => /Orden de Reparacion origen identificada/.test(output)));
  assert.equal(factOf(real("HP-REP-003"), "origin_order_finished"), true);
});

check("4) se identifica/referencia el Detalle origen (035 output, 075 + BR-REP-019)", () => {
  const node = nodeById.get("PROC-REP-035");
  assert.ok((node?.outputs ?? []).some((output) => /Detalle\(s\) origen/.test(output)));
  assert.ok((nodeById.get("PROC-REP-075")?.rules ?? []).includes("BR-REP-019"));
  assert.match(desc("PROC-REP-075"), /Detalle origen/);
  assert.match(ruleText("BR-REP-019"), /Detalle original/);
  assert.equal(factOf(real("HP-REP-003"), "origin_detail_identified"), true);
  assert.equal(expectedOf(real("HP-REP-003"), "new_detail_linked_to_origin_detail"), true);
});

check("5) se crea una NUEVA Orden vinculada (035 -> 040, BR-REP-019)", () => {
  const order = orderOf(real("HP-REP-003"));
  assert.ok(order.indexOf("PROC-REP-035") < order.indexOf("PROC-REP-040"));
  assert.match(desc("PROC-REP-040"), /NUEVA Orden/);
  assert.ok((nodeById.get("PROC-REP-040")?.rules ?? []).includes("BR-REP-019"));
  assert.match(ruleText("BR-REP-019"), /NUEVA Orden vinculada/);
  assert.equal(expectedOf(real("HP-REP-003"), "new_order_linked_to_origin_order"), true);
});

check("6) la Orden anterior no se reabre (ni estado nuevo tipo REABIERTA_POR_GARANTIA)", () => {
  assert.equal(expectedOf(real("HP-REP-003"), "origin_order_reopened"), false);
  assert.equal(expectedOf(real("HP-REP-003"), "origin_order_state_unchanged"), true);
  assert.match(ruleText("BR-REP-019"), /NO se reabre/);
  const everything = JSON.stringify(real("HP-REP-003")) + ruleText("BR-REP-019");
  assert.ok(!/REABIERTA_POR_GARANTIA|ORIGINAL_EN_GARANTIA/.test(everything.replace(/no se crean estados como REABIERTA_POR_GARANTIA/g, "")));
});

check("7) el origen es RMA_GARANTIA_REPARACION", () => {
  assert.equal(factOf(real("HP-REP-003"), "origin"), "RMA_GARANTIA_REPARACION");
});

check("8) la condicion comercial es NO_COBRABLE (hecho y BR-REP-016; se aprueba en 265)", () => {
  assert.equal(factOf(real("HP-REP-003"), "origin_billing_condition"), "NO_COBRABLE");
  assert.match(ruleText("BR-REP-016"), /RMA_GARANTIA_REPARACION[^.]*NO_COBRABLE|NO_COBRABLE[^.]*RMA_GARANTIA_REPARACION/);
  assert.equal(factOf(real("HP-REP-003"), "delivery_condition_approved_by"), "NO_COBRABLE_POR_ORIGEN");
});

check("9) no recorre registro de cliente/equipo nuevo (030) ni otros origenes; recupera de la origen", () => {
  const nodes = traversedNodes(real("HP-REP-003"));
  for (const skipped of ["PROC-REP-030", "PROC-REP-020", "PROC-REP-025", "PROC-REP-010"]) assert.ok(!nodes.has(skipped), skipped);
  assert.equal(factOf(real("HP-REP-003"), "new_customer_equipment_registration"), false);
  assert.equal(factOf(real("HP-REP-003"), "customer_equipment_recovered_from_origin"), true);
});

check("10) no recorre pagos", () => {
  assert.ok(!traversedNodes(real("HP-REP-003")).has("PROC-REP-266"));
  assert.ok(!real("HP-REP-003").steps.some((s) => s.kind === "FUNCTIONAL_ACTION"));
  assert.equal(factOf(real("HP-REP-003"), "payment_required"), false);
  assert.equal(expectedOf(real("HP-REP-003"), "payment_registered"), false);
});

check("11) recorre PROC-REP-265 como validacion de condicion de entrega, pero nunca 266 ni pagos", () => {
  const scenario = real("HP-REP-003");
  const nodes = traversedNodes(scenario);
  assert.ok(nodes.has("PROC-REP-265"), "recorre PROC-REP-265");
  assert.ok(!nodes.has("PROC-REP-266"), "no entra en PROC-REP-266");
  assert.ok(scenario.steps.some((s) => isProcessEdgeStep(s) && s.from === "PROC-REP-265" && s.to === "PROC-REP-280" && s.condition === "Si"));
  assert.ok(!scenario.steps.some((s) => isProcessEdgeStep(s) && s.from === "PROC-REP-265" && s.to === "PROC-REP-266"));
  assert.equal(factOf(scenario, "delivery_condition_gate_traversed"), true);
  assert.equal(expectedOf(scenario, "delivery_condition_approved"), true);
  assert.ok(!(scenario.skipped_nodes ?? []).some((n) => n.node === "PROC-REP-265"), "265 no esta omitido");
  assert.ok((scenario.skipped_nodes ?? []).some((n) => n.node === "PROC-REP-266"), "266 esta omitido");
});

check("11b) la condicion de entrega se aprueba por origen NO_COBRABLE: sin saldo mediante pagos, sin anticipo, sin cortesia", () => {
  const scenario = real("HP-REP-003");
  assert.equal(factOf(scenario, "delivery_condition_approved_by"), "NO_COBRABLE_POR_ORIGEN");
  assert.equal(factOf(scenario, "balance_via_payments_required"), false);
  assert.equal(factOf(scenario, "courtesy_used_to_avoid_charge"), false);
  assert.equal(factOf(scenario, "payment_required"), false);
  assert.match(desc("PROC-REP-265"), /RMA_GARANTIA_REPARACION[\s\S]*NO_COBRABLE|NO_COBRABLE[\s\S]*RMA_GARANTIA_REPARACION/);
  assert.match(desc("PROC-REP-265"), /no existe un bypass/i);
  assert.match(ruleText("BR-REP-016"), /recorre PROC-REP-265/);
  assert.match(ruleText("BR-REP-017"), /mismo gate de condicion de entrega/);
});

check("12) mantiene price snapshot (075) sin que implique pago", () => {
  assert.ok(traversedNodes(real("HP-REP-003")).has("PROC-REP-075"));
  assert.equal(factOf(real("HP-REP-003"), "price_snapshot_registered"), true);
  assert.equal(factOf(real("HP-REP-003"), "payment_required"), false);
  assert.match(desc("PROC-REP-075"), /precio registrado no implica/i);
});

check("12b) la revision tecnica es obligatoria: 045 No -> 055 -> ... -> 065 -> 068 Si -> 075, nunca 070", () => {
  const scenario = real("HP-REP-003");
  const order = orderOf(scenario);
  for (const node of ["PROC-REP-055", "PROC-REP-065", "PROC-REP-068", "PROC-REP-075"]) {
    assert.ok(order.includes(node), node);
  }
  assert.ok(!traversedNodes(scenario).has("PROC-REP-070"), "no copia el Tipo origen por 070");
  assert.ok(order.indexOf("PROC-REP-065") < order.indexOf("PROC-REP-075"));
  assert.equal(factOf(scenario, "details_known_at_intake"), false);
  assert.equal(factOf(scenario, "technical_review_required"), true);
  assert.equal(expectedOf(scenario, "technical_review_completed"), true);
  assert.match(ruleText("BR-REP-019"), /revision tecnica/);
});

check("13) recorre notificacion al cliente (260)", () => {
  assert.ok(traversedNodes(real("HP-REP-003")).has("PROC-REP-260"));
  assert.equal(expectedOf(real("HP-REP-003"), "client_notified"), true);
});

check("14) recorre documentacion final y entrega al cliente: 260 -> 265 -> 280 -> 270 [-> 268 en V1.4]", () => {
  const order = orderOf(real("HP-REP-003"));
  assert.deepEqual(order.slice(V14 ? -7 : -6), withGate(["PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-280", "PROC-REP-270", "EVT-REP-999"]));
  assert.equal(expectedOf(real("HP-REP-003"), "equipment_delivered_to_client"), true);
  assert.equal(factOf(real("HP-REP-003"), "client_delivery_required"), true);
});

check("15) no recorre el informe a Gestion RT propio de RT_INTERNO (290)", () => {
  assert.ok(!traversedNodes(real("HP-REP-003")).has("PROC-REP-290"));
});

check("16) llega a EVT-REP-999", () => {
  const order = orderOf(real("HP-REP-003"));
  assert.equal(order[order.length - 1], "EVT-REP-999");
});

check("17) ningun nodo esta en steps[] y en skipped_nodes de HP-REP-003", () => {
  const nodes = traversedNodes(real("HP-REP-003"));
  assert.ok((real("HP-REP-003").skipped_nodes ?? []).length > 0);
  for (const skipped of real("HP-REP-003").skipped_nodes ?? []) {
    assert.ok(!nodes.has(skipped.node), skipped.node);
    assert.ok(skipped.reason.trim().length > 0);
  }
});

check("18) todas las referencias (nodes/edges/features/reglas) de HP-REP-003 son validas", () => {
  assert.deepEqual(errorsOf(real("HP-REP-003")), []);
  const ruleIds = new Set(rulesModel.rules.map((rule) => rule.id));
  for (const nodeId of traversedNodes(real("HP-REP-003"))) {
    for (const ruleId of nodeById.get(nodeId)?.rules ?? []) assert.ok(ruleIds.has(ruleId), `${nodeId} -> ${ruleId}`);
  }
  assert.ok(ruleIds.has("BR-REP-019"));
});

check("19) HP-REP-001 sigue pasando (misma ruta de cobro, sin cambios)", () => {
  assert.deepEqual(errorsOf(real("HP-REP-001")), []);
  const edges = real("HP-REP-001").steps.filter(isProcessEdgeStep);
  assert.ok(edges.some((s) => s.from === "PROC-REP-260" && s.to === "PROC-REP-265" && s.condition === undefined));
  assert.ok(!traversedNodes(real("HP-REP-001")).has("PROC-REP-035"));
});

check("20) HP-REP-002 sigue pasando (290 -> 270 [-> 268 en V1.4] -> fin, sin cobro)", () => {
  assert.deepEqual(errorsOf(real("HP-REP-002")), []);
  assert.deepEqual(orderOf(real("HP-REP-002")).slice(V14 ? -5 : -4), withGate(["PROC-REP-250", "PROC-REP-290", "PROC-REP-270", "EVT-REP-999"]));
});

check("no hay bypass alrededor de 265: 260 solo llega a 265 y 280 solo se alcanza desde 265", () => {
  const outOf260 = processModel.edges.filter((edge) => edge.from === "PROC-REP-260");
  assert.deepEqual(outOf260.map((edge) => edge.to), ["PROC-REP-265"]);
  const into280 = processModel.edges.filter((edge) => edge.to === "PROC-REP-280");
  assert.deepEqual(into280.map((edge) => edge.from), ["PROC-REP-265"]);
  assert.deepEqual(processModel.edges.filter((edge) => edge.to === "PROC-REP-266").map((edge) => edge.from), ["PROC-REP-265"]);
});

check("Features activas de HP-REP-003 = 001..008 (sin 009), con razones reales", () => {
  const { activeFeatureIds, activationReasons } = deriveScenarioFeatures(featuresModel, real("HP-REP-003"));
  assert.deepEqual(activeFeatureIds, [1, 2, 3, 4, 5, 6, 7, 8].map((n) => `FEAT-REP-00${n}`));
  assert.ok(activationReasons["FEAT-REP-001"].some((r) => r.includes("PROC-REP-035")));
  // FEAT-REP-007: own node 265 (delivery-condition gate) plus shared ALWAYS nodes (075, 280); never its own 266.
  // La garantia RMA define sus Detalles luego de la revision obligatoria (075), nunca por 070.
  const r7 = activationReasons["FEAT-REP-007"];
  assert.ok(r7.some((r) => r.includes("nodo propio PROC-REP-265")));
  assert.ok(r7.some((r) => r.includes("PROC-REP-075") && r.includes("(ALWAYS)")));
  assert.ok(r7.some((r) => r.includes("PROC-REP-280") && r.includes("(ALWAYS)")));
  assert.ok(!r7.some((r) => r.includes("PROC-REP-266")));
});

check("HP-REP-003 converge con HP-REP-001 desde PROC-REP-080 (tras la revision obligatoria)", () => {
  const a = orderOf(real("HP-REP-001"));
  const b = orderOf(real("HP-REP-003"));
  const tail = (o: string[], from: string, to: string): string[] => o.slice(o.indexOf(from), o.indexOf(to) + 1);
  // V1.4: HP-REP-001 (origen RECEPCION) suma la evaluacion tecnica 183; HP-REP-003 (REVISION_TECNICA) no la requiere
  const noEval = (o: string[]): string[] => o.filter((n) => !["PROC-REP-182", "PROC-REP-183", "PROC-REP-184"].includes(n));
  assert.deepEqual(noEval(tail(b, "PROC-REP-080", "PROC-REP-260")), noEval(tail(a, "PROC-REP-080", "PROC-REP-260")));
});

console.log("\nCasos negativos del validador\n");

check("nodo inexistente", () => {
  const s = clone("HP-REP-002");
  (s.steps[1] as { to: string }).to = "PROC-REP-999";
  expectError(s, 'to inexistente "PROC-REP-999"');
});

check("edge inexistente (par sin transicion)", () => {
  const s = clone("HP-REP-002");
  (s.steps[2] as { to: string }).to = "PROC-REP-150";
  expectError(s, "no existe ninguna transicion");
});

check("condicion distinta a la del process", () => {
  const s = clone("HP-REP-002");
  (s.steps[1] as { condition?: string }).condition = "CLIENTE_EXTERNO";
  expectError(s, "no coincide con el process");
});

check("condicion inventada donde el edge no tiene", () => {
  const s = clone("HP-REP-002");
  (s.steps[0] as { condition?: string }).condition = "inventada";
  expectError(s, "no coincide con el process");
});

check("salto imposible (continuidad rota)", () => {
  const s = clone("HP-REP-002");
  s.steps.splice(3, 1);
  expectError(s, "continuidad rota");
});

check("Happy Path sin inicio", () => {
  const s = clone("HP-REP-002");
  s.steps.shift();
  expectError(s, "debe comenzar en");
});

check("Happy Path sin fin", () => {
  const s = clone("HP-REP-002");
  s.steps.pop();
  expectError(s, "debe terminar en");
});

check("Happy Path sin steps de proceso", () => {
  const s = clone("HP-REP-002");
  s.steps = [];
  expectError(s, "sin ningun step PROCESS_EDGE");
});

check("IDs de Scenario duplicados", () => {
  assert.deepEqual(findDuplicateIds([{ id: "A" }, { id: "A" }, { id: "B" }] as Scenario[]), ["A"]);
});

check("FUNCTIONAL_ACTION con Feature inexistente", () => {
  const s = clone("HP-REP-001");
  const action = s.steps.find((step) => step.kind === "FUNCTIONAL_ACTION") as { feature: string };
  action.feature = "FEAT-REP-999";
  expectError(s, 'feature inexistente "FEAT-REP-999"');
});

check("skipped_nodes: nodo inexistente", () => {
  const s = clone("HP-REP-002");
  s.skipped_nodes = [{ node: "PROC-REP-999", reason: "x" }];
  expectError(s, 'skipped_nodes: node inexistente "PROC-REP-999"');
});

check("skipped_nodes: nodo a la vez incluido y omitido (p. ej. 270 en HP-REP-002)", () => {
  const s = clone("HP-REP-002");
  s.skipped_nodes = [{ node: "PROC-REP-270", reason: "x" }];
  expectError(s, "included y skipped a la vez");
});

check("skipped_nodes: duplicado", () => {
  const s = clone("HP-REP-002");
  s.skipped_nodes = [
    { node: "PROC-REP-030", reason: "x" },
    { node: "PROC-REP-030", reason: "y" },
  ];
  expectError(s, "node duplicado");
});

console.log("\nArquitectura de Variant/Exception (forma generica, con datos sinteticos)\n");

const ajv = new Ajv({ allErrors: true, strict: false });
const validateSchema = ajv.compile(JSON.parse(readFileSync(SCHEMA_FILE, "utf8")));

function syntheticVariant(overrides: Partial<Scenario> = {}): Scenario {
  return {
    id: "VAR-TEST-001",
    name: "Variant sintetica de prueba",
    type: "VARIANT",
    scope: "FEATURE",
    status: "draft",
    source_process: { id: "PROC-REP", version: "1.3" },
    description: "Solo para probar la forma; no forma parte del modelo real.",
    feature: "FEAT-REP-001",
    applies_to: ["HP-REP-001"],
    trigger: { node: "PROC-REP-010", edge: { from: "PROC-REP-010", to: "PROC-REP-030", condition: "CLIENTE_EXTERNO" } },
    affected_nodes: ["PROC-REP-265", "PROC-REP-270"],
    rules: ["BR-REP-016"],
    dependencies: { requires: [], enables: [], implies: [], excludes: [] },
    ...overrides,
  } as Scenario;
}

check("el schema acepta una Variant sin steps/facts/expected", () => {
  const ok = validateSchema({ process: { id: "PROC-REP", version: "1.3" }, scenarios: [syntheticVariant()] });
  assert.ok(ok, JSON.stringify(validateSchema.errors));
});

check("el schema sigue exigiendo steps/facts/expected a un HAPPY_PATH", () => {
  const hp = syntheticVariant({ type: "HAPPY_PATH", scope: "E2E" });
  assert.ok(!validateSchema({ process: { id: "PROC-REP", version: "1.3" }, scenarios: [hp] }));
});

check("una Variant con referencias validas no produce errores", () => {
  const variant = syntheticVariant();
  const map = new Map(scenariosById);
  map.set(variant.id, variant);
  assert.deepEqual(validateScenario(variant, processModel, featureIds, map), []);
});

check("Variant: referencias rotas se detectan (feature, trigger, applies_to, dependencies)", () => {
  const variant = syntheticVariant({
    feature: "FEAT-REP-999",
    trigger: { node: "PROC-REP-999" },
    affected_nodes: ["PROC-REP-998"],
    applies_to: ["HP-REP-999"],
    dependencies: { requires: ["VAR-NOPE"], excludes: ["VAR-TEST-001"] },
  });
  const map = new Map(scenariosById);
  map.set(variant.id, variant);
  const errors = validateScenario(variant, processModel, featureIds, map);
  for (const fragment of [
    'feature inexistente "FEAT-REP-999"',
    'trigger.node inexistente "PROC-REP-999"',
    'affected_nodes: node inexistente "PROC-REP-998"',
    'applies_to: scenario inexistente "HP-REP-999"',
    'dependencies.requires: scenario inexistente "VAR-NOPE"',
    "no puede depender de si mismo",
  ]) {
    assert.ok(errors.some((e) => e.includes(fragment)), `falta error "${fragment}" en ${JSON.stringify(errors)}`);
  }
});

console.log("\nMVP v2 - Scenarios reales (VARIANT/EXCEPTION), confirmados desde el discovery\n");

// V1.4 adds VAR-REP-004 to 009 (customer decision per Detalle and desistance).
const MVP_V2_VARIANT_IDS =
  REVISION === "v1.4"
    ? [
        "VAR-REP-001",
        "VAR-REP-002",
        "VAR-REP-003",
        "VAR-REP-004",
        "VAR-REP-005",
        "VAR-REP-006",
        "VAR-REP-007",
        "VAR-REP-008",
        "VAR-REP-009",
        "VAR-REP-010",
        "VAR-REP-011",
        "VAR-REP-012",
        "VAR-REP-013",
        "VAR-REP-014",
        "VAR-REP-015",
        "VAR-REP-016",
        "VAR-REP-017",
        "VAR-REP-018",
        "VAR-REP-019",
        "VAR-REP-020",
        "VAR-REP-021",
        "VAR-REP-022",
        "VAR-REP-023",
        "VAR-REP-024",
        "VAR-REP-025",
        "VAR-REP-026",
        "VAR-REP-027",
        "VAR-REP-028",
        "VAR-REP-029",
        // AUD-V14-001: saldo a favor del cliente y devolucion de dinero (BR-REP-038)
        "VAR-REP-030",
        "VAR-REP-031",
        "VAR-REP-032",
        "VAR-REP-033",
        "VAR-REP-034",
        "VAR-REP-035",
        // iteracion 10: autorizacion parcial en una Orden ya habilitada sin omitir la factibilidad (AUD-V14-003)
        "VAR-REP-036",
        // consolidacion del 23/10/2026: decisiones confirmadas (ver business/decisions/decision-log-v1.4.yaml)
        "VAR-REP-037",
        "VAR-REP-038",
        "VAR-REP-039",
        "VAR-REP-040",
        "VAR-REP-041",
        "VAR-REP-042",
        "VAR-REP-043",
      ]
    : ["VAR-REP-001", "VAR-REP-002", "VAR-REP-003"];
const MVP_V2_EXCEPTION_IDS = [
  "EXC-REP-001",
  "EXC-REP-002",
  "EXC-REP-003",
  "EXC-REP-004",
  "EXC-REP-005",
];
const MVP_V2_HAPPY_PATH_IDS = ["HP-REP-001", "HP-REP-002", "HP-REP-003"];

check("el scope es exactamente los HAPPY_PATH + VARIANT + 5 EXCEPTION esperados (MVP v2; +VAR-REP-004..036 en V1.4), sin EDGE_CASE", () => {
  const byType = (type: Scenario["type"]): string[] =>
    scenariosModel.scenarios.filter((s) => s.type === type).map((s) => s.id).sort();
  assert.deepEqual(byType("HAPPY_PATH"), [...MVP_V2_HAPPY_PATH_IDS].sort());
  assert.deepEqual(byType("VARIANT"), [...MVP_V2_VARIANT_IDS].sort());
  assert.deepEqual(byType("EXCEPTION"), [...MVP_V2_EXCEPTION_IDS].sort());
  assert.deepEqual(byType("EDGE_CASE"), []);
  assert.equal(scenariosModel.scenarios.length, REVISION === "v1.4" ? 51 : 11);
});

check("todos los IDs de Scenario son unicos", () => {
  assert.deepEqual(findDuplicateIds(scenariosModel.scenarios), []);
});

for (const id of [...MVP_V2_VARIANT_IDS, ...MVP_V2_EXCEPTION_IDS]) {
  check(`${id}: valida sin errores, applies_to solo referencia Happy Paths reales`, () => {
    const scenario = real(id);
    assert.deepEqual(errorsOf(scenario), []);
    assert.ok((scenario.applies_to ?? []).length > 0, `${id} debe declarar applies_to`);
    for (const target of scenario.applies_to ?? []) {
      assert.ok(MVP_V2_HAPPY_PATH_IDS.includes(target), `${id}: applies_to "${target}" no es uno de los 3 Happy Paths de MVP v2`);
    }
  });

  check(`${id}: nodos/edges de steps[] y trigger existen en el Process Graph real`, () => {
    const scenario = real(id);
    assert.ok((scenario.steps ?? []).length > 0, `${id} debe declarar steps[]`);
    const nodeIds = new Set(processModel.nodes.map((node) => node.id));
    for (const step of scenario.steps ?? []) {
      if (isProcessEdgeStep(step)) {
        assert.ok(nodeIds.has(step.from), `${id}: from inexistente ${step.from}`);
        assert.ok(nodeIds.has(step.to), `${id}: to inexistente ${step.to}`);
      }
    }
    assert.ok(scenario.trigger, `${id} debe declarar trigger`);
    assert.ok(nodeIds.has(scenario.trigger!.node), `${id}: trigger.node inexistente`);
  });

  check(`${id}: rules[] y feature declarados existen`, () => {
    const scenario = real(id);
    const ruleIds = new Set(rulesModel.rules.map((rule) => rule.id));
    for (const ruleId of scenario.rules ?? []) assert.ok(ruleIds.has(ruleId), `${id}: BR inexistente ${ruleId}`);
    if (scenario.feature) assert.ok(featureIds.has(scenario.feature), `${id}: Feature inexistente ${scenario.feature}`);
  });
}

check("tipo correcto: los 3 VARIANT son type=VARIANT, las 5 EXCEPTION son type=EXCEPTION", () => {
  for (const id of MVP_V2_VARIANT_IDS) assert.equal(real(id).type, "VARIANT", id);
  for (const id of MVP_V2_EXCEPTION_IDS) assert.equal(real(id).type, "EXCEPTION", id);
});

check("VAR-REP-001/002 son la misma trayectoria de negocio (EN_REVISION al ingreso) con y sin comprobante", () => {
  assert.equal(real("VAR-REP-001").trigger?.node, "PROC-REP-045");
  assert.equal(real("VAR-REP-002").trigger?.node, "PROC-REP-045");
  assert.ok(traversedNodes(real("VAR-REP-001")).has("PROC-REP-060"), "con comprobante pasa por 060");
  assert.ok(!traversedNodes(real("VAR-REP-002")).has("PROC-REP-060"), "sin comprobante (RT_INTERNO) no pasa por 060");
  // En HP-REP-003 la revision es obligatoria (BR-REP-019): VAR-REP-001 ya no aplica a la garantia RMA.
  assert.deepEqual(real("VAR-REP-001").applies_to, ["HP-REP-001"]);
  assert.deepEqual(real("VAR-REP-002").applies_to, ["HP-REP-002"]);
});

check("SIN_REPARACION tras EN_REVISION (CAND-REP-010/017) no es un Scenario propio: es el desenlace 068 No -> 069 de la revision (FEAT-REP-002)", () => {
  // Unica excepcion declarada (AUD-V14-001): VAR-REP-030 recorre 069 porque su objeto NO es el desenlace SIN_REPARACION
  // sino su consecuencia comercial (saldo a favor del cliente por un anticipo, FEAT-REP-007, BR-REP-038).
  const COMMERCIAL_CONSEQUENCE_OF_SIN_REPARACION = V14 ? ["VAR-REP-030"] : [];
  for (const id of [...MVP_V2_VARIANT_IDS, ...MVP_V2_EXCEPTION_IDS].filter((x) => !COMMERCIAL_CONSEQUENCE_OF_SIN_REPARACION.includes(x))) {
    assert.ok(!traversedNodes(real(id)).has("PROC-REP-069"), `${id} no deberia llegar a PROC-REP-069 (SIN_REPARACION)`);
  }
  for (const id of COMMERCIAL_CONSEQUENCE_OF_SIN_REPARACION) {
    assert.equal(real(id).feature, "FEAT-REP-007", `${id} pertenece a la Feature comercial, no a la revision`);
    assert.ok(traversedNodes(real(id)).has("PROC-REP-267"), `${id} se justifica por el saldo a favor (PROC-REP-267)`);
  }
});

check("Recursos insuficientes es DELIBERADAMENTE 2 Scenarios (espera vs. override), no fusionados", () => {
  const wait = real("EXC-REP-001");
  const override = real("EXC-REP-002");
  assert.deepEqual(wait.trigger, override.trigger, "comparten el mismo punto de divergencia (090)");
  assert.notDeepEqual(
    (wait.steps ?? []).map((s) => JSON.stringify(s)),
    (override.steps ?? []).map((s) => JSON.stringify(s)),
    "pero sus steps[] literales son distintos: el schema no permite dos recorridos en un solo steps[]"
  );
  assert.equal(override.rules?.includes("BR-REP-003"), true, "el override cita BR-REP-003 (ya existente, sin regla nueva)");
});

check("mecanica multi-Detalle (CAND-REP-028/029/030) sigue sin convertirse en Scenario real", () => {
  // PROC-REP-212 ("¿Iniciar un Detalle de reparacion?") es parte del recorrido base de todo Happy Path
  // en V1.4 (cambio del MVP, DC04): se alcanza desde PROC-REP-180, asi que 212::Si::181 ya no es un
  // mecanismo exclusivo de Multi-Detalle. Sigue siendo mecanico llegar a 212 DESDE 211 y decidir liberar
  // (212::No::213); la unica excepcion declarada es VAR-REP-037 (liberacion de una toma ajena, DC04).
  const mechanismEdges = new Set([
    "PROC-REP-211::Existe Detalle trabajable, sin toma activa::PROC-REP-170",
    "PROC-REP-211::Existe Detalle trabajable, toma activa::PROC-REP-212",
    ...(V14 ? [] : ["PROC-REP-212::Si::PROC-REP-181"]),
    "PROC-REP-212::No::PROC-REP-213",
  ]);
  const CROSS_RELEASE = V14 ? ["VAR-REP-037"] : [];
  for (const scenario of scenariosModel.scenarios.filter((s) => !CROSS_RELEASE.includes(s.id))) {
    for (const step of scenario.steps ?? []) {
      if (!isProcessEdgeStep(step)) continue;
      const key = `${step.from}::${step.condition ?? ""}::${step.to}`;
      assert.ok(!mechanismEdges.has(key), `${scenario.id} no deberia declarar el mecanismo ${key} como Scenario propio`);
    }
  }
});

check("RT_GARANTIA_VENTA sigue OUT_OF_SCOPE de MVP v2: ningun Scenario lo menciona", () => {
  for (const scenario of scenariosModel.scenarios) {
    const text = JSON.stringify(scenario);
    assert.ok(!text.includes("RT_GARANTIA_VENTA"), `${scenario.id} no deberia mencionar RT_GARANTIA_VENTA`);
  }
});

check("los 3 Happy Paths de MVP v2 no fueron alterados por los nuevos Scenarios", () => {
  for (const id of MVP_V2_HAPPY_PATH_IDS) assert.deepEqual(errorsOf(real(id)), []);
  assert.deepEqual(orderOf(real("HP-REP-001")).slice(0, 2), ["EVT-REP-001", "PROC-REP-010"]);
  assert.deepEqual(orderOf(real("HP-REP-002")).slice(0, 2), ["EVT-REP-001", "PROC-REP-010"]);
  assert.deepEqual(orderOf(real("HP-REP-003")).slice(0, 2), ["EVT-REP-002", "PROC-REP-035"]);
});

if (REVISION === "v1.4") {
  console.log("\nV1.4 - FEAT-REP-001/002/003/005/008/009: ingreso, autorizacion por Detalle, altas del tecnico, resolver, custodia y devolucion; sin regresiones\n");

  const OTHER = "Origen distinto de CLIENTE_EXTERNO";
  // V1.3 se compara con los nombres de estado del Detalle de la consolidacion (DC17): el renombre
  // PENDIENTE -> DEFINIDO / EN_PROCESO -> EN_PROGRESO no cuenta como diferencia.
  const asConsolidated = <T>(model: T): T => JSON.parse(renameLegacyDetailStates(JSON.stringify(model))) as T;
  const v13Process = asConsolidated(loadYaml<ProcessModel>("business/processes/repair-management-v1.3.yaml"));
  const v13Rules = asConsolidated(loadYaml<{ rules: { id: string; description?: string }[] }>("business/rules/business-rules-v1.3.yaml"));
  const v13Scenarios = asConsolidated(loadYaml<ScenarioModel>("business/scenarios/repair-management-scenarios-v1.3.yaml"));
  const key = (edge: { from: string; to: string; condition?: string }): string =>
    `${edge.from}::${edge.condition ?? ""}::${edge.to}`;
  const outgoing = (from: string): string[] =>
    processModel.edges.filter((e) => e.from === from).map((e) => `${e.condition ?? ""}->${e.to}`).sort();
  const reachableFrom = (start: string): string[] => {
    const seen = new Set<string>();
    const queue = [start];
    while (queue.length > 0) {
      const node = queue.shift() as string;
      if (seen.has(node)) continue;
      seen.add(node);
      for (const e of processModel.edges.filter((edge) => edge.from === node)) queue.push(e.to);
    }
    return [...seen];
  };
  // PROC-REP-267 se comparte entre la validacion de entrega (265) y la verificacion previa al fin (268): su salida
  // "Devolucion registrada, validar ..." depende de desde donde se llego (idioma de salidas rotuladas por contexto,
  // como PROC-REP-270). El alcance topologico puro cruza contextos; este recorrido respeta la salida rotulada.
  const reachableInContext = (start: string): string[] => {
    const seen = new Set<string>();
    const visited = new Set<string>();
    const queue: Array<{ node: string; prev: string }> = [{ node: start, prev: "" }];
    while (queue.length > 0) {
      const { node, prev } = queue.shift() as { node: string; prev: string };
      const state = node + "<" + prev;
      if (visited.has(state)) continue;
      visited.add(state);
      seen.add(node);
      for (const e of processModel.edges.filter((edge) => edge.from === node)) {
        if (node === "PROC-REP-267") {
          const returnsToDelivery = e.to === "PROC-REP-265";
          if (returnsToDelivery !== (prev === "PROC-REP-265")) continue;
        }
        queue.push({ node: e.to, prev: node });
      }
    }
    return [...seen];
  };
  const featureNodes = (id: string): string[] => featuresModel.features.find((f) => f.id === id)?.process_nodes ?? [];
  const rule = (id: string): string => rulesModel.rules.find((r) => r.id === id)?.description ?? "";
  const nodeText = (id: string): string => nodeById.get(id)?.description ?? "";

  check("DC17: V1.4 nombra los estados del Detalle DEFINIDO, EN_PROGRESO, COMPLETO y CANCELADO, sin nombres anteriores", () => {
    for (const file of [PROCESS_FILE, FEATURES_FILE, SCENARIOS_FILE, `business/rules/business-rules-${REVISION}.yaml`]) {
      assert.deepEqual(legacyDetailStateUses(readFileSync(file, "utf8")), [], file);
    }
    assert.match(rule("BR-REP-012"), /Estados operativos del Detalle:\s+DEFINIDO, EN_PROGRESO, COMPLETO y CANCELADO/);
    assert.match(rule("BR-REP-012"), /DEFINIDO -> EN_PROGRESO al reservar e\s+iniciar la Ejecucion \(PROC-REP-185\)/);
    assert.match(rule("BR-REP-012"), /un COMPLETO nunca pasa a CANCELADO/);
  });

  check("integridad del grafo V1.4: sin nodos sin salida, sin nodos inalcanzables y sin IDs duplicados", () => {
    const ids = processModel.nodes.map((n) => n.id);
    assert.equal(ids.length, new Set(ids).size);
    const hasOut = new Set(processModel.edges.map((e) => e.from));
    const hasIn = new Set(processModel.edges.map((e) => e.to));
    for (const node of processModel.nodes) {
      if (node.type !== "end") assert.ok(hasOut.has(node.id), `${node.id} sin salida`);
      if (node.type !== "event" && node.type !== "start") assert.ok(hasIn.has(node.id), `${node.id} inalcanzable`);
    }
    const reachable = new Set(["EVT-REP-001", "EVT-REP-002", "EVT-REP-003"].flatMap((start) => reachableFrom(start)));
    for (const node of processModel.nodes) assert.ok(reachable.has(node.id), `${node.id} no es alcanzable desde un evento de inicio`);
  });

  check("FEAT-REP-001 termina en PROC-REP-032: 030 -> 040 -> 032 -> 045 (sin decision, sin comprobante, sin cancelacion)", () => {
    const order = orderOf(real("HP-REP-001"));
    const at = order.indexOf("PROC-REP-030");
    assert.deepEqual(order.slice(at, at + 4), ["PROC-REP-030", "PROC-REP-040", "PROC-REP-032", "PROC-REP-045"]);
    assert.deepEqual(outgoing("PROC-REP-032"), ["->PROC-REP-045"]);
    const f1 = featureNodes("FEAT-REP-001");
    for (const moved of ["PROC-REP-046", "PROC-REP-047", "PROC-REP-050", "PROC-REP-056", "PROC-REP-060", "PROC-REP-128", "PROC-REP-129", "PROC-REP-306"]) {
      assert.ok(!f1.includes(moved), `FEAT-REP-001 no debe poseer ${moved}`);
    }
    const f1Rules = featuresModel.features.find((f) => f.id === "FEAT-REP-001")?.business_rules ?? [];
    for (let n = 27; n <= 34; n++) assert.ok(!f1Rules.includes(`BR-REP-0${n}`), `FEAT-REP-001 no declara BR-REP-0${n}`);
  });

  check("el Process Graph V1.4 difiere de V1.3 SOLO en los nodos/edges declarados", () => {
    const v13Keys = new Set(v13Process.edges.map(key));
    const v14Keys = new Set(processModel.edges.map(key));
    assert.deepEqual([...v13Keys].filter((k) => !v14Keys.has(k)).sort(), [
      "PROC-REP-035::::PROC-REP-040",
      "PROC-REP-040::::PROC-REP-045",
      "PROC-REP-055::::PROC-REP-050",
      "PROC-REP-070::::PROC-REP-050",
      "PROC-REP-075::::PROC-REP-080",
      "PROC-REP-090::Existe Detalle trabajable::PROC-REP-140",
      "PROC-REP-090::Ninguno trabajable::PROC-REP-100",
      "PROC-REP-127::::PROC-REP-080",
      "PROC-REP-180::::PROC-REP-181",
      "PROC-REP-181::::PROC-REP-174",
      "PROC-REP-211::Todos cancelados::EVT-REP-999",
      "PROC-REP-265::No::PROC-REP-266",
      "PROC-REP-270::::EVT-REP-999",
      "PROC-REP-300::::PROC-REP-211",
    ]);
    assert.deepEqual(
      [...v14Keys].filter((k) => !v13Keys.has(k)).sort(),
      [
        "PROC-REP-032::::PROC-REP-045",
        "PROC-REP-040::CLIENTE_EXTERNO::PROC-REP-032",
        "PROC-REP-040::RMA_GARANTIA_REPARACION::PROC-REP-045",
        "PROC-REP-040::RT_GARANTIA_VENTA::PROC-REP-045",
        "PROC-REP-040::RT_INTERNO::PROC-REP-045",
        "PROC-REP-046::Decision del cliente registrada::PROC-REP-047",
        "PROC-REP-046::Solicitud sin resolver, Detalles siguen pendientes de autorizacion::PROC-REP-211",
        "PROC-REP-047::Acepta trabajos::PROC-REP-211",
        "PROC-REP-047::Rechaza algunos Detalles::PROC-REP-300",
        "PROC-REP-047::Rechaza todos los trabajos::PROC-REP-305",
        "PROC-REP-055::CLIENTE_EXTERNO::PROC-REP-056",
        "PROC-REP-056::Acepta la revision tecnica::PROC-REP-050",
        "PROC-REP-056::Desiste sin Detalles::PROC-REP-306",
        `PROC-REP-055::${OTHER}::PROC-REP-050`,
        "PROC-REP-070::CLIENTE_EXTERNO::PROC-REP-046",
        `PROC-REP-070::${OTHER}::PROC-REP-050`,
        "PROC-REP-075::CLIENTE_EXTERNO::PROC-REP-046",
        `PROC-REP-075::${OTHER}::PROC-REP-080`,
        "PROC-REP-090::Orden ya habilitada::PROC-REP-211",
        "PROC-REP-090::Primera habilitacion, existe Detalle trabajable::PROC-REP-140",
        "PROC-REP-090::Primera habilitacion, ninguno trabajable::PROC-REP-100",
        "PROC-REP-127::Redefinicion posterior a una Ejecucion, CLIENTE_EXTERNO::PROC-REP-046",
        "PROC-REP-127::Redefinicion posterior a una Ejecucion, origen distinto de CLIENTE_EXTERNO::PROC-REP-080",
        "PROC-REP-127::Redefinicion durante la evaluacion tecnica::PROC-REP-184",
        "PROC-REP-300::Cancelacion fuera de la evaluacion tecnica::PROC-REP-211",
        "PROC-REP-300::Descarte durante la evaluacion tecnica::PROC-REP-184",
        "PROC-REP-128::Alta durante la ejecucion, CLIENTE_EXTERNO::PROC-REP-190",
        "EVT-REP-003::::PROC-REP-046",
        "PROC-REP-128::Alta durante la ejecucion, origen distinto de CLIENTE_EXTERNO::PROC-REP-080",
        "PROC-REP-128::Alta durante la evaluacion tecnica::PROC-REP-184",
        "PROC-REP-129::::PROC-REP-046",
        "PROC-REP-190::Detecta reparacion adicional::PROC-REP-128",
        "PROC-REP-211::Antes del comprobante de recepcion::PROC-REP-050",
        "PROC-REP-211::Comprobante emitido, factibilidad pendiente::PROC-REP-080",
        "PROC-REP-211::Ejecucion activa vigente::PROC-REP-190",
        "PROC-REP-211::PENDIENTE_AUTORIZACION::PROC-REP-129",
        "PROC-REP-211::Todos cancelados, sin equipo bajo custodia::PROC-REP-268",
        "PROC-REP-211::Todos cancelados, equipo bajo custodia::PROC-REP-270",
        "PROC-REP-306::Sin equipo bajo custodia::PROC-REP-268",
        "PROC-REP-306::Equipo bajo custodia::PROC-REP-270",
        "PROC-REP-306::Custodia sin confirmar::PROC-REP-271",
        "PROC-REP-271::Equipo bajo custodia::PROC-REP-270",
        "PROC-REP-271::Sin equipo bajo custodia::PROC-REP-268",
        // V1.4 saldo a favor del cliente (AUD-V14-001, BR-REP-038)
        "PROC-REP-265::No, saldo pendiente de cobro::PROC-REP-266",
        "PROC-REP-265::No, saldo a favor del cliente::PROC-REP-267",
        "PROC-REP-267::Devolucion registrada, validar entrega::PROC-REP-265",
        "PROC-REP-267::Devolucion registrada, validar fin de Orden::PROC-REP-268",
        "PROC-REP-268::Sin saldo a favor pendiente::EVT-REP-999",
        "PROC-REP-268::Saldo a favor del cliente pendiente de devolver::PROC-REP-267",
        "PROC-REP-270::::PROC-REP-268",
        "PROC-REP-211::Todos cancelados, custodia sin confirmar::PROC-REP-271",
        "PROC-REP-181::::PROC-REP-182",
        // consolidacion: la toma conduce a la decision de iniciar un Detalle o liberar (cambio del MVP, DC04)
        "PROC-REP-180::::PROC-REP-212",
        // consolidacion: la garantia RMA valida la vigencia de origen antes de crear la Orden (DC15B)
        "PROC-REP-035::::PROC-REP-036",
        "PROC-REP-036::Vigente::PROC-REP-040",
        "PROC-REP-036::Vencida, excepcion autorizada::PROC-REP-040",
        "PROC-REP-036::Vencida, sin excepcion::EVT-REP-998",
        // consolidacion: la entrega con trabajos realizados exige el check-in (UAT-009)
        "PROC-REP-265::Saldo en 0, falta el check-in::PROC-REP-269",
        "PROC-REP-269::Revalidar::PROC-REP-265",
        // consolidacion DC07: la cancelacion efectiva de un desistimiento solicitado, despues de interrumpir
        "PROC-REP-211::Desistimiento solicitado de un Detalle ya interrumpido::PROC-REP-300",
        "PROC-REP-211::Desistimiento total solicitado, sin Ejecucion activa::PROC-REP-305",
        "PROC-REP-182::No requiere evaluacion tecnica::PROC-REP-174",
        "PROC-REP-182::Requiere evaluacion tecnica::PROC-REP-183",
        "PROC-REP-183::CONFIRMADO::PROC-REP-184",
        "PROC-REP-183::DESCARTADO::PROC-REP-300",
        "PROC-REP-183::REQUIERE_REDEFINICION::PROC-REP-127",
        "PROC-REP-184::Otra reparacion adicional por registrar::PROC-REP-128",
        "PROC-REP-184::Hay Detalles pendientes de factibilidad (origen distinto de CLIENTE_EXTERNO)::PROC-REP-080",
        "PROC-REP-184::Original CONFIRMADO, sin Detalles pendientes de factibilidad::PROC-REP-182",
        "PROC-REP-184::Original cancelado o redefinido, sin Detalles pendientes de factibilidad::PROC-REP-211",
      ].sort()
    );
    const v13Ids = new Set(v13Process.nodes.map((n) => n.id));
    assert.deepEqual(
      processModel.nodes.map((n) => n.id).filter((id) => !v13Ids.has(id)),
      ["PROC-REP-032", "PROC-REP-036", "PROC-REP-046", "PROC-REP-047", "PROC-REP-056", "PROC-REP-128", "PROC-REP-129", "PROC-REP-182", "PROC-REP-183", "PROC-REP-184", "PROC-REP-271", "PROC-REP-267", "PROC-REP-268", "PROC-REP-269", "PROC-REP-306", "EVT-REP-003", "EVT-REP-998"]
    );
    const changed = v13Process.nodes
      .filter((n) => JSON.stringify(n) !== JSON.stringify(nodeById.get(n.id)))
      .map((n) => n.id);
    // 010, 069, 125, 130, 140, 170 and the rest stay untouched (120 gains the stock revalidation, BR-REP-049).
    assert.deepEqual(
      changed.sort(),
      [
        "PROC-REP-030", "PROC-REP-040", "PROC-REP-045", "PROC-REP-050", "PROC-REP-060", "PROC-REP-070", "PROC-REP-075", "PROC-REP-080", "PROC-REP-090", "PROC-REP-127", "PROC-REP-150", "PROC-REP-172", "PROC-REP-174", "PROC-REP-181", "PROC-REP-185", "PROC-REP-190", "PROC-REP-211", "PROC-REP-265", "PROC-REP-266", "PROC-REP-270", "PROC-REP-280", "PROC-REP-300", "PROC-REP-305",
        // consolidacion del 23/10/2026: cambios del MVP y decisiones DC03 a DC05
        "PROC-REP-180", "PROC-REP-212", "PROC-REP-213", "PROC-REP-245",
        // DC15B, DC19, DC20 y UAT
        "PROC-REP-035", "PROC-REP-120",
        // comercial, documentos y comunicaciones (DC13, DC25, DC26, DC30, UAT-008/009)
        "PROC-REP-260",
        // cancelaciones durante ejecuciones (DC07)
        "PROC-REP-200",
        // texto del fin corregido: su unica entrada es PROC-REP-268 (DC17, AUD-V14-016)
        "EVT-REP-999",
      ].sort()
    );
  });

  check("la autorizacion es una sola capacidad (046/047) con cuatro entradas (070, 075, 127, 128) mas la espera 129 y EVT-REP-003, solo CLIENTE_EXTERNO; la Orden sin Detalles (055) NO la invoca", () => {
    // iteracion 10: sin Detalles no hay nada que autorizar: 055 -> 056 (continuar con la revision), nunca 046
    assert.ok(outgoing("PROC-REP-055").includes("CLIENTE_EXTERNO->PROC-REP-056"));
    assert.ok(!outgoing("PROC-REP-055").some((o) => o.endsWith("->PROC-REP-046")), "055 ya no consulta al cliente por Detalle");
    for (const from of ["PROC-REP-070", "PROC-REP-075"]) {
      const out = processModel.edges.filter((e) => e.from === from).map((e) => `${e.condition}->${e.to}`);
      assert.ok(out.includes("CLIENTE_EXTERNO->PROC-REP-046"), `${from} -> 046 [CLIENTE_EXTERNO]`);
      assert.ok(out.some((o) => o.startsWith(OTHER + "->")), `${from} conserva la salida de los demas origenes`);
    }
    assert.ok(outgoing("PROC-REP-127").includes("Redefinicion posterior a una Ejecucion, CLIENTE_EXTERNO->PROC-REP-046"));
    assert.ok(outgoing("PROC-REP-127").includes("Redefinicion posterior a una Ejecucion, origen distinto de CLIENTE_EXTERNO->PROC-REP-080"));
    // 128 y 184: la quinta entrada y la evaluacion tecnica, con condiciones excluyentes por contexto
    const out128 = outgoing("PROC-REP-128");
    assert.ok(out128.includes("Alta durante la ejecucion, CLIENTE_EXTERNO->PROC-REP-190"), "la alta no espera la consulta");
    assert.ok(out128.includes("Alta durante la ejecucion, origen distinto de CLIENTE_EXTERNO->PROC-REP-080"));
    assert.deepEqual(outgoing("EVT-REP-003"), ["->PROC-REP-046"], "carril propio de Recepcion");
    assert.deepEqual(outgoing("PROC-REP-129"), ["->PROC-REP-046"]);
    assert.deepEqual(outgoing("PROC-REP-046"), [
      "Decision del cliente registrada->PROC-REP-047",
      "Solicitud sin resolver, Detalles siguen pendientes de autorizacion->PROC-REP-211",
    ].sort());
    // PROC-REP-047: EXACTAMENTE tres decisiones de negocio; ninguna condicion interna es una eleccion del cliente
    assert.deepEqual(outgoing("PROC-REP-047"), [
      "Acepta trabajos->PROC-REP-211",
      "Rechaza algunos Detalles->PROC-REP-300",
      "Rechaza todos los trabajos->PROC-REP-305",
    ].sort());
    for (const internal of ["PROC-REP-050", "PROC-REP-080", "PROC-REP-306"]) {
      assert.ok(!outgoing("PROC-REP-047").some((o) => o.endsWith(`->${internal}`)), `047 no enruta directamente a ${internal}`);
    }
    assert.ok(!outgoing("PROC-REP-047").some((o) => /Sin respuesta|Desiste|comprobante|factibilidad/i.test(o)), "ni sin respuesta, ni desistimiento sin Detalles, ni condiciones internas");
    assert.equal(nodeById.get("PROC-REP-046")?.actor, "ACT-RECEP");
    assert.equal(nodeById.get("PROC-REP-047")?.type, "decision");
    for (const id of ["PROC-REP-046", "PROC-REP-047", "PROC-REP-050", "PROC-REP-060", "PROC-REP-128", "PROC-REP-129"]) {
      assert.ok(featureNodes("FEAT-REP-002").includes(id), `FEAT-REP-002 posee ${id}`);
    }
  });

  check("alta de Detalle por el tecnico (128): ACT-TECH, REVISION_TECNICA, pendiente de autorizacion, sin interrumpir la Ejecucion, sin reutilizar 075", () => {
    assert.equal(nodeById.get("PROC-REP-128")?.actor, "ACT-TECH");
    assert.ok(outgoing("PROC-REP-190").includes("Detecta reparacion adicional->PROC-REP-128"));
    assert.ok(outgoing("PROC-REP-190").includes("->PROC-REP-200"), "190 -> 200 sigue siendo el recorrido por defecto");
    assert.deepEqual(outgoing("PROC-REP-128"), ["Alta durante la ejecucion, origen distinto de CLIENTE_EXTERNO->PROC-REP-080", "Alta durante la ejecucion, CLIENTE_EXTERNO->PROC-REP-190", "Alta durante la evaluacion tecnica->PROC-REP-184"].sort());
    assert.ok(!processModel.edges.some((e) => e.from === "PROC-REP-128" && ["PROC-REP-075", "PROC-REP-211", "PROC-REP-200", "PROC-REP-185"].includes(e.to)));
    const d = nodeText("PROC-REP-128");
    assert.match(d, /REVISION_TECNICA/);
    assert.match(d, /PENDIENTE_AUTORIZACION/);
    assert.match(d, /NO puede iniciarlo/);
    assert.match(d, /Ejecuciones activas NO se\s+interrumpen/);
    assert.match(d, /No reutiliza\s+PROC-REP-075/);
    const r = rule("BR-REP-032");
    assert.match(r, /no interrumpe las\s+Ejecuciones activas/);
    assert.match(r, /no reserva ni consume\s+insumos/);
    assert.match(r, /estacion/);
  });

  check("un Detalle sin autorizacion no se ejecuta: 181/185 y 080 lo excluyen, y no bloquea a los demas (BR-REP-028)", () => {
    for (const id of ["PROC-REP-181", "PROC-REP-185", "PROC-REP-080"]) {
      assert.ok((nodeById.get(id)?.rules ?? []).includes("BR-REP-028"), `${id} cita BR-REP-028`);
    }
    assert.match(nodeText("PROC-REP-181"), /no es trabajable y no se puede\s+seleccionar ni iniciar/);
    assert.match(nodeText("PROC-REP-185"), /no reserva ni consume insumos/);
    assert.match(nodeText("PROC-REP-080"), /no se confunde stock disponible con\s+autorizacion/);
    const r = rule("BR-REP-028");
    assert.match(r, /tres dimensiones independientes/);
    assert.match(r, /PENDIENTE_AUTORIZACION es una condicion derivada de la\s+autorizacion y NO un estado operativo/);
    assert.match(r, /no puede\s+ejecutarse/);
    assert.match(r, /NO bloquea a los demas\s+Detalles/);
    assert.match(r, /No existe una autorizacion general de la Orden/);
    for (const f of ["FEAT-REP-003", "FEAT-REP-005"]) {
      assert.ok(featuresModel.features.find((x) => x.id === f)?.business_rules.includes("BR-REP-028"), f);
    }
  });

  check("resolver (BR-REP-012 V1.4): conserva el texto V1.3, agrega PENDIENTE_AUTORIZACION y los bloqueos sin estados combinados; casos A a H", () => {
    const v13 = v13Rules.rules.find((r) => r.id === "BR-REP-012")?.description ?? "";
    const v14 = rule("BR-REP-012");
    assert.ok(v14.startsWith(v13.trimEnd().slice(0, 200)), "empieza igual que V1.3");
    assert.ok(v14.includes(v13.trimEnd().slice(-120)), "conserva el cierre del texto V1.3");
    assert.match(v14, /5 REQUIERE_REVISION; 6 PENDIENTE_AUTORIZACION/);
    assert.match(v14, /7 PENDIENTE_RECURSOS \(antes prioridad\s+6\)/);
    assert.match(v14, /CONTEXTO_INCONSISTENTE, que sigue sin ser un estado de\s+negocio/);
    assert.match(v14, /BLOQUEOS/);
    assert.match(v14, /Se\s+evitan estados combinados/);
    for (const c of ["A)", "B)", "C)", "D)", "E)", "F)", "G)", "H)"]) assert.ok(v14.includes(c), `caso ${c}`);
    assert.match(v14, /C\) COMPLETO\s+\+ pendiente -> PENDIENTE_AUTORIZACION/);
    assert.match(v14, /D\) COMPLETO \+ el resto CANCELADO -> COMPLETA/);
    assert.match(v14, /E\)\s+todos CANCELADO -> TODO_CANCELADO/);
    assert.match(v14, /PENDIENTE_AUTORIZACION,\s+PENDIENTE_RECURSOS\]/);
    assert.match(v14, /decision de negocio\s+aprobada: REQUIERE_REVISION > PENDIENTE_AUTORIZACION >\s+PENDIENTE_RECURSOS/);
    assert.ok(!/provisional/i.test(v14), "la precedencia ya no es provisional");
    assert.ok(!/PENDIENTE_RECURSOS_Y_AUTORIZACION/.test(v14));
  });

  check("enrutamiento separado del resolver (BR-REP-034): 211 elige la estacion por situacion Y hitos, 090 no re-habilita una Orden habilitada", () => {
    assert.deepEqual(outgoing("PROC-REP-211"), [
      "Antes del comprobante de recepcion->PROC-REP-050",
      "Comprobante emitido, factibilidad pendiente->PROC-REP-080",
      "Desistimiento solicitado de un Detalle ya interrumpido->PROC-REP-300",
      "Desistimiento total solicitado, sin Ejecucion activa->PROC-REP-305",
      "Ejecucion activa vigente->PROC-REP-190",
      "Existe Detalle trabajable, sin toma activa->PROC-REP-170",
      "Existe Detalle trabajable, toma activa->PROC-REP-212",
      "PENDIENTE_AUTORIZACION->PROC-REP-129",
      "PENDIENTE_RECURSOS->PROC-REP-120",
      "REQUIERE_REVISION->PROC-REP-125",
      "Todos cancelados, sin equipo bajo custodia->PROC-REP-268",
      "Todos cancelados, equipo bajo custodia->PROC-REP-270",
      "Todos cancelados, custodia sin confirmar->PROC-REP-271",
      "Todos terminales, existe completo->PROC-REP-220",
    ].sort());
    assert.ok(!outgoing("PROC-REP-211").some((o) => o.startsWith("Orden sin habilitar")), "condicion generica reemplazada");
    assert.deepEqual(outgoing("PROC-REP-090"), [
      "Primera habilitacion, existe Detalle trabajable->PROC-REP-140",
      "Primera habilitacion, ninguno trabajable->PROC-REP-100",
      "Orden ya habilitada->PROC-REP-211",
    ].sort());
    const t = rule("BR-REP-034");
    assert.match(t, /separadas/);
    assert.match(t, /no vuelve a\s+habilitarla, pedir prioridad ni encolarla/);
    assert.match(t, /sin\s+reiniciar el ingreso ni invalidar hitos previos/);
    assert.match(t, /nunca se considera trabajable solo\s+porque haya stock/);
    assert.match(nodeText("PROC-REP-211"), /RESOLVER y el ENRUTAMIENTO se\s+separan/);
    assert.match(nodeText("PROC-REP-211"), /toma activa se cierra automaticamente tambien en este caso/);
  });

  check("PROC-REP-040 bifurca por origen igual que PROC-REP-010: solo CLIENTE_EXTERNO va a 032", () => {
    const conditions010 = processModel.edges.filter((e) => e.from === "PROC-REP-010").map((e) => e.condition).sort();
    const out040 = processModel.edges.filter((e) => e.from === "PROC-REP-040");
    assert.deepEqual(out040.map((e) => e.condition).sort(), conditions010);
    for (const edge of out040) {
      assert.equal(edge.to, edge.condition === "CLIENTE_EXTERNO" ? "PROC-REP-032" : "PROC-REP-045", String(edge.condition));
    }
    const into040 = processModel.edges.filter((e) => e.to === "PROC-REP-040").map((e) => e.from).sort();
    // la garantia RMA llega a 040 desde la validacion de vigencia (vigente o excepcion autorizada, DC15B)
    assert.deepEqual(into040, ["PROC-REP-020", "PROC-REP-025", "PROC-REP-030", "PROC-REP-036", "PROC-REP-036"]);
  });

  check("regresion otros origenes: HP-REP-002 y HP-REP-003 no pasan por 032/046/047/128/129/306 y conservan su recorrido", () => {
    for (const id of ["HP-REP-002", "HP-REP-003"]) {
      for (const node of ["PROC-REP-032", "PROC-REP-046", "PROC-REP-047", "PROC-REP-056", "PROC-REP-128", "PROC-REP-129", "PROC-REP-306"]) {
        assert.ok(!traversedNodes(real(id)).has(node), `${id} no debe recorrer ${node}`);
      }
      for (const node of ["PROC-REP-032", "PROC-REP-046", "PROC-REP-047"]) {
        assert.ok((real(id).skipped_nodes ?? []).some((s) => s.node === node), `${id} declara ${node} omitido`);
      }
    }
    const o2 = orderOf(real("HP-REP-002"));
    assert.deepEqual(o2.slice(o2.indexOf("PROC-REP-020"), o2.indexOf("PROC-REP-020") + 5), ["PROC-REP-020", "PROC-REP-040", "PROC-REP-045", "PROC-REP-070", "PROC-REP-050"]);
    const o3 = orderOf(real("HP-REP-003"));
    assert.deepEqual(o3.slice(0, 9), ["EVT-REP-002", "PROC-REP-035", "PROC-REP-036", "PROC-REP-040", "PROC-REP-045", "PROC-REP-055", "PROC-REP-050", "PROC-REP-060", "PROC-REP-065"]);
    assert.ok(processModel.edges.some((e) => key(e) === "PROC-REP-040::RT_GARANTIA_VENTA::PROC-REP-045"));
    assert.deepEqual(outgoing("PROC-REP-010"), [
      "CLIENTE_EXTERNO->PROC-REP-030",
      "RMA_GARANTIA_REPARACION->PROC-REP-035",
      "RT_GARANTIA_VENTA->PROC-REP-025",
      "RT_INTERNO->PROC-REP-020",
    ]);
    // Other origins take no client decision at the entry points that are shared with CLIENTE_EXTERNO.
    assert.match(rule("BR-REP-028"), /RT_INTERNO, RT_GARANTIA_VENTA y\s+RMA_GARANTIA_REPARACION\s+conservan su comportamiento anterior/);
  });

  // Reglas de V1.3 que V1.4 cambia, cada una con su motivo: las iteraciones V1.4 (012, 017, 019) y las
  // decisiones de la consolidacion del 23/10/2026 (DCxx). Todas las demas deben seguir identicas a V1.3.
  // Reglas nuevas de la consolidacion del 23/10/2026, en orden.
  const CONSOLIDATION_RULES = Array.from({ length: 11 }, (_, i) => `BR-REP-0${39 + i}`);
  const V13_RULES_CHANGED_IN_V14: Record<string, string> = {
    "BR-REP-003": "DC06: el tecnico redefine (PROC-REP-127); redaccion del estado DEFINIDO (DC17)",
    "BR-REP-004": "DC07B: interrumpir para cancelar registra estado, materiales y reversibilidad; motivo de interrupcion (UAT)",
    "BR-REP-009": "DC05: puntaje total derivado, PROC-REP-245 consolida (texto del MVP)",
    "BR-REP-011": "Estacion = Mesa de trabajo; override con permiso configurable (DC08)",
    "BR-REP-015": "DC23AUD: historial de precios auditado; precio manual de \"Otros\" (UAT)",
    "BR-REP-016": "DC09: Ajuste Comercial unificado (CORTESIA o DESCUENTO) por Orden o por Detalle",
    "BR-REP-012": "parrafo V1.4 (autorizacion y bloqueos) y estados del Detalle (DC17)",
    "BR-REP-014": "DC07A a DC07D y DC08: cancelacion por Detalle durante ejecuciones, proceso guiado y tipos",
    "BR-REP-017": "parrafo V1.4 de saldo a favor (BR-REP-038); formula unica, anulacion (DC10) y cortesia total (DC11)",
    "BR-REP-018": "DC04: liberar antes del primer Detalle (texto del MVP) y liberacion de una toma ajena",
    "BR-REP-019": "responsable de PROC-REP-075; vigencia de la garantia de origen (DC15B)",
  };
  check(`reglas: BR-REP-001 a 019 identicas a V1.3 salvo las declaradas (${Object.keys(V13_RULES_CHANGED_IN_V14).join(", ")}); +19 nuevas (020 a 038)`, () => {
    const v13ById = new Map(v13Rules.rules.map((r) => [r.id, r]));
    // aprobar la baseline (DC01, 24/10/2026) cambia el status de las reglas V1.4 de draft a approved, no su contenido
    const content = (r: object | undefined): object => ({ ...r, status: undefined });
    assert.ok(rulesModel.rules.every((r) => (r as { status?: string }).status === "approved"), "DC01: todas las reglas V1.4 estan aprobadas");
    for (const r of rulesModel.rules.filter((x) => v13ById.has(x.id) && !(x.id in V13_RULES_CHANGED_IN_V14))) {
      assert.deepEqual(content(r), content(v13ById.get(r.id)), r.id);
    }
    // BR-REP-017 conserva el texto V1.3 y solo agrega el parrafo de saldo a favor (BR-REP-038)
    const r17 = rulesModel.rules.find((x) => x.id === "BR-REP-017");
    const v17 = v13ById.get("BR-REP-017");
    const flat = (t: string | undefined): string => (t ?? "").replace(/\s+/g, " ").trim();
    // la consolidacion deja una sola formula de Saldo y aclara la cortesia total (DC11); el resto del texto V1.3 se conserva
    const v17n = flat(v17?.description)
      .replace("y se calcula el Saldo = Total Cobrable - Total Pagado (PROC-REP-265)", "y se calcula el Saldo con la formula unica de BR-REP-038 (PROC-REP-265)")
      .replace("ENTREGADA cuando Saldo = 0 o cuando corresponde cortesia total de Orden;", "ENTREGADA cuando Saldo = 0 (una cortesia total sin Pagos recibidos deja Saldo = 0);");
    assert.ok(flat(r17?.description).startsWith(v17n), "BR-REP-017 conserva el texto V1.3 salvo la formula y la cortesia total");
    assert.match(flat(r17?.description), /BR-REP-038/);
    assert.deepEqual(content({ ...r17, description: "" }), content({ ...v17, description: "" }));
    // BR-REP-019 solo cambia el responsable de PROC-REP-075 (Recepcion -> tecnico)
    const r19 = rulesModel.rules.find((x) => x.id === "BR-REP-019");
    const v19 = v13ById.get("BR-REP-019");
    const norm = (t: string | undefined): string => (t ?? "").replace(/\s+/g, " ");
    // ademas, DC15B resuelve el pendiente de garantia vencida: el resto del texto V1.3 se conserva
    const r19n = norm(r19?.description).replace("el tecnico define y registra uno o mas Detalles nuevos", "Recepcion define uno o mas Detalles nuevos");
    const [v19Before, v19After] = norm(v19?.description).split(" Queda pendiente definir las reglas de garantia RMA configurable y de garantia vencida.");
    assert.ok(v19After !== undefined, "V1.3 declaraba pendiente la garantia vencida");
    assert.ok(r19n.startsWith(v19Before) && r19n.endsWith(v19After), "BR-REP-019 conserva el texto V1.3 salvo el pendiente que resuelve DC15B");
    assert.match(r19n, /se advierte y se bloquea el ingreso en garantia, salvo una excepcion autorizada/);
    assert.deepEqual(content({ ...r19, description: "" }), content({ ...v19, description: "" }));
    // +19 de las iteraciones V1.4 (020 a 038) y las nuevas de la consolidacion desde BR-REP-039
    assert.equal(rulesModel.rules.length, v13Rules.rules.length + 19 + CONSOLIDATION_RULES.length);
    assert.deepEqual(rulesModel.rules.slice(v13Rules.rules.length + 19).map((r) => r.id), CONSOLIDATION_RULES);
    const declared = (f: string): string[] => featuresModel.features.find((x) => x.id === f)?.business_rules ?? [];
    for (let n = 20; n <= 26; n++) assert.ok(declared("FEAT-REP-001").includes(`BR-REP-0${n}`), `FEAT-REP-001 declara BR-REP-0${n}`);
    for (const id of ["BR-REP-027", "BR-REP-028", "BR-REP-029", "BR-REP-030", "BR-REP-031", "BR-REP-032", "BR-REP-033"]) assert.ok(declared("FEAT-REP-002").includes(id), `FEAT-REP-002 declara ${id}`);
    for (const id of ["BR-REP-027", "BR-REP-030", "BR-REP-033"]) assert.ok(declared("FEAT-REP-009").includes(id), `FEAT-REP-009 declara ${id}`);
    assert.ok(declared("FEAT-REP-008").includes("BR-REP-033"));
    assert.ok(declared("FEAT-REP-003").includes("BR-REP-034"));
    assert.ok(declared("FEAT-REP-007").includes("BR-REP-038"), "FEAT-REP-007 declara BR-REP-038");
    assert.ok(declared("FEAT-REP-008").includes("BR-REP-038"), "FEAT-REP-008 declara BR-REP-038");
  });

  check("la advertencia (BR-REP-025) vive en PROC-REP-032 y no se confunde con la autorizacion del cliente (046/047)", () => {
    assert.ok((nodeById.get("PROC-REP-032")?.rules ?? []).includes("BR-REP-025"));
    assert.ok(!(nodeById.get("PROC-REP-040")?.rules ?? []).includes("BR-REP-025"));
    assert.ok(!(nodeById.get("PROC-REP-047")?.rules ?? []).includes("BR-REP-025"));
    const text = rule("BR-REP-025");
    assert.match(text, /intenta AVANZAR/);
    assert.match(text, /nunca\s+bloquea/);
    // DC12: tambien se advierte por verificaciones faltantes del checklist (antes no)
    assert.match(text, /tambien\s+se advierte cuando faltan verificaciones del checklist/);
    assert.match(text, /decision del cliente sobre los trabajos \(BR-REP-028\)/);
    const save = rule("BR-REP-023");
    assert.match(save, /guardarse parcialmente y retomarse/);
    assert.match(save, /NO avanza el workflow ni crea un estado de\s+negocio nuevo/);
  });

  check("revalidacion (BR-REP-029): toda 127 requiere decision nueva, los Detalles sin cambios la conservan, y un alta del tecnico tambien", () => {
    const d29 = rule("BR-REP-029");
    assert.match(d29, /NO se extiende\s+automaticamente/);
    assert.match(d29, /no se invalida innecesariamente/);
    assert.match(d29, /PROC-REP-128/);
    assert.match(d29, /sin\s+regenerar el comprobante/);
    assert.match(nodeText("PROC-REP-127"), /vuelve a PROC-REP-046 para una nueva decision antes de\s+PROC-REP-080/);
    assert.match(nodeText("PROC-REP-075"), /la aceptacion previa de la revision NO los autoriza/);
  });

  check("desistimiento: individual (047 -> 300), masivo (047 -> 305) y sin Detalles (056 -> 306, propio de esa etapa); 300/305/306 no duplican nodos", () => {
    for (const [id, from, edgeText] of [
      ["VAR-REP-005", "PROC-REP-047", "Rechaza algunos Detalles->PROC-REP-300"],
      ["VAR-REP-006", "PROC-REP-047", "Rechaza todos los trabajos->PROC-REP-305"],
      ["VAR-REP-004", "PROC-REP-056", "Desiste sin Detalles->PROC-REP-306"],
    ] as const) {
      assert.ok(outgoing(from).includes(edgeText), edgeText);
      assert.equal(real(id).trigger?.node, from, id);
    }
    assert.deepEqual(outgoing("PROC-REP-056"), ["Acepta la revision tecnica->PROC-REP-050", "Desiste sin Detalles->PROC-REP-306"].sort(), "056 conserva la via de desistimiento sin Detalles, separada de la autorizacion por Detalle");
    const f9 = featureNodes("FEAT-REP-009");
    assert.deepEqual(f9.filter((n) => n.startsWith("PROC-REP-30")).sort(), ["PROC-REP-300", "PROC-REP-305", "PROC-REP-306"]);
    assert.ok(!processModel.nodes.some((n) => /cancel/i.test(n.name) && !f9.includes(n.id)), "no hay otro nodo de cancelacion");
  });

  check("cancelacion parcial antes de habilitar: a 050 (antes del comprobante) o a 080 (comprobante emitido), nunca a la cola ni a 140", () => {
    const early = orderOf(real("VAR-REP-005"));
    assert.ok(!early.includes("PROC-REP-170") && !early.includes("PROC-REP-140"));
    assert.deepEqual(early.slice(-3), ["PROC-REP-300", "PROC-REP-211", "PROC-REP-050"]);
    const late = orderOf(real("VAR-REP-013"));
    assert.deepEqual(late.slice(-3), ["PROC-REP-300", "PROC-REP-211", "PROC-REP-080"]);
    assert.ok(!late.includes("PROC-REP-170") && !late.includes("PROC-REP-050"));
  });

  check("custodia (BR-REP-033): el comprobante (060) es la recepcion fisica; sin comprobante no hay devolucion; con comprobante, la Orden CANCELADA pasa por 270", () => {
    assert.match(nodeText("PROC-REP-060"), /documento que se intercambia por el\s+equipo fisico/);
    assert.match(nodeText("PROC-REP-060"), /creacion de\s+la Orden no implica que el equipo este en el taller/);
    const c = rule("BR-REP-033");
    assert.match(c, /no se requiere devolucion fisica/);
    assert.match(c, /no finaliza\s+operativamente mientras un equipo recibido permanezca sin devolucion/);
    assert.match(c, /fecha\/hora, usuario que entrega y\s+persona que recibe/);
    assert.match(c, /no convierte CANCELADA en ENTREGADA/);
    assert.match(c, /no se crean estados operativos del Detalle/);
    // VAR-REP-004 / 006: desisten antes del comprobante => no recibido => fin directo, sin 270
    for (const id of ["VAR-REP-004", "VAR-REP-006"]) {
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-270"), `${id} no requiere devolucion`);
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-060"), `${id} no emitio comprobante`);
      assert.equal(orderOf(real(id)).at(-1), "EVT-REP-999");
    }
    // VAR-REP-007: el comprobante ya se entrego => equipo recibido => 211 -> 270 -> fin
    const o7 = orderOf(real("VAR-REP-007"));
    assert.deepEqual(o7.slice(-4), ["PROC-REP-211", "PROC-REP-270", "PROC-REP-268", "EVT-REP-999"]);
    assert.equal(expectedOf(real("VAR-REP-007"), "marked_delivered"), false);
    assert.equal(expectedOf(real("VAR-REP-007"), "equipment_return_registered"), true);
    // A cancelled order can never reach commercial delivery (la salida de 267 respeta el contexto de entrada)
    for (const bad of ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-280", "PROC-REP-220"]) {
      assert.ok(!reachableInContext("PROC-REP-306").includes(bad), `306 no alcanza ${bad}`);
    }
    assert.match(nodeText("PROC-REP-270"), /Cuarto contexto/);
    assert.match(nodeText("PROC-REP-270"), /no convierte CANCELADA en ENTREGADA/);
    assert.match(nodeText("PROC-REP-270"), /Una Orden con\s+algun Detalle COMPLETO no entra por este camino/);
  });

  check("VAR-REP-004: desiste sin Detalles (056), sin comprobante -> 306 -> fin directo (equipo no recibido); sin consulta por Detalle, reparacion, control, notificacion, cobro ni SIN_REPARACION", () => {
    const scenario = real("VAR-REP-004");
    assert.deepEqual(scenario.applies_to, ["HP-REP-001"]);
    assert.deepEqual(orderOf(scenario).slice(-5), ["PROC-REP-055", "PROC-REP-056", "PROC-REP-306", "PROC-REP-268", "EVT-REP-999"]);
    const nodes = traversedNodes(scenario);
    for (const forbidden of ["PROC-REP-046", "PROC-REP-047", "PROC-REP-050", "PROC-REP-060", "PROC-REP-069", "PROC-REP-070", "PROC-REP-075", "PROC-REP-090", "PROC-REP-185", "PROC-REP-200", "PROC-REP-210", "PROC-REP-211", "PROC-REP-220", "PROC-REP-240", "PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-270", "PROC-REP-280", "PROC-REP-300", "PROC-REP-305"]) {
      assert.ok(!nodes.has(forbidden), `VAR-REP-004 no debe recorrer ${forbidden}`);
    }
    assert.equal(factOf(scenario, "detail_count"), 0);
    assert.equal(factOf(scenario, "equipment_received"), false);
    assert.equal(expectedOf(scenario, "workflow_state"), "CANCELADA");
    assert.equal(expectedOf(scenario, "marked_delivered"), false);
    assert.equal(expectedOf(scenario, "equipment_return_registered"), false);
    assert.equal(expectedOf(scenario, "reception_receipt_generated"), false);
    assert.deepEqual(reachableInContext("PROC-REP-306").sort(), ["EVT-REP-999", "PROC-REP-267", "PROC-REP-268", "PROC-REP-270", "PROC-REP-271", "PROC-REP-306"]);
    assert.equal(nodeById.get("PROC-REP-306")?.actor, undefined, "actor no definido por negocio");
  });

  check("tecnico agrega un Detalle (VAR-REP-010/011): la Ejecucion vigente continua (211 -> 190), la Orden no se re-habilita ni se encola", () => {
    const o10 = orderOf(real("VAR-REP-010"));
    // "Acepta trabajos" vuelve al resolver, que enruta a factibilidad ("Comprobante emitido, factibilidad pendiente"), y de alli a 090 -> 211 -> 190
    assert.deepEqual(o10, ["EVT-REP-003", "PROC-REP-046", "PROC-REP-047", "PROC-REP-211", "PROC-REP-080", "PROC-REP-090", "PROC-REP-211", "PROC-REP-190"]);
    for (const bad of ["PROC-REP-140", "PROC-REP-150", "PROC-REP-170", "PROC-REP-200", "PROC-REP-050"]) assert.ok(!o10.includes(bad), `VAR-REP-010 no recorre ${bad}`);
    assert.equal(expectedOf(real("VAR-REP-010"), "active_execution_interrupted"), false);
    assert.equal(expectedOf(real("VAR-REP-010"), "new_detail_startable_before_feasibility"), false);
    assert.equal(expectedOf(real("VAR-REP-010"), "inventory_reserved_before_authorization"), false);
    assert.equal(factOf(real("VAR-REP-010"), "new_detail_diagnosis_origin"), "REVISION_TECNICA");
    assert.equal(factOf(real("VAR-REP-010"), "customer_decision"), "AUTORIZA");
    const o11 = orderOf(real("VAR-REP-011"));
    assert.deepEqual(o11, ["EVT-REP-003", "PROC-REP-046", "PROC-REP-047", "PROC-REP-300", "PROC-REP-211", "PROC-REP-190"]);
    assert.equal(expectedOf(real("VAR-REP-011"), "rejected_detail_state"), "CANCELADO");
  });

  check("espera de autorizacion (VAR-REP-012) y bloqueo mixto (VAR-REP-014): sin control final ni cola, sin estado combinado", () => {
    const o12 = orderOf(real("VAR-REP-012"));
    assert.ok(o12.includes("PROC-REP-129") && !o12.includes("PROC-REP-220") && !o12.includes("PROC-REP-170"));
    assert.equal(expectedOf(real("VAR-REP-012"), "order_goes_to_technical_control"), false);
    assert.equal(expectedOf(real("VAR-REP-012"), "order_enters_queue"), false);
    assert.equal(factOf(real("VAR-REP-012"), "resolver_situation"), "PENDIENTE_AUTORIZACION");
    const s14 = real("VAR-REP-014");
    assert.equal(factOf(s14, "first_resolver_blockers"), "PENDIENTE_AUTORIZACION,PENDIENTE_RECURSOS");
    assert.equal(factOf(s14, "first_resolver_situation"), "PENDIENTE_AUTORIZACION");
    assert.equal(expectedOf(s14, "combined_state_created"), false);
    assert.equal(expectedOf(s14, "second_resolver_situation"), "PENDIENTE_RECURSOS");
    assert.deepEqual(orderOf(s14).slice(-2), ["PROC-REP-211", "PROC-REP-120"]);
  });

  check("redefinicion: 127 -> 046 para CLIENTE_EXTERNO (VAR-REP-008/009); EXC-REP-004 acotado a los demas origenes", () => {
    assert.deepEqual(real("EXC-REP-004").applies_to, ["HP-REP-002", "HP-REP-003"]);
    assert.deepEqual(orderOf(real("VAR-REP-008")).slice(-5), ["PROC-REP-127", "PROC-REP-046", "PROC-REP-047", "PROC-REP-211", "PROC-REP-080"]);
    assert.deepEqual(orderOf(real("VAR-REP-009")).slice(-3), ["PROC-REP-300", "PROC-REP-211", "PROC-REP-220"]);
    assert.equal(factOf(real("VAR-REP-009"), "completed_details"), 1);
    assert.equal(expectedOf(real("VAR-REP-009"), "completed_detail_preserved"), true);
  });

  check("comprobante: despues de la decision inicial, una sola vez, nunca tras 075/127/128 ni si desiste", () => {
    // con Detalles conocidos: la aceptacion de los trabajos (047) precede al comprobante, que enruta el sistema (211 -> 050)
    const hp = orderOf(real("HP-REP-001"));
    assert.ok(hp.indexOf("PROC-REP-047") < hp.indexOf("PROC-REP-050"), "HP-REP-001: decision antes del comprobante");
    assert.deepEqual(hp.slice(hp.indexOf("PROC-REP-047"), hp.indexOf("PROC-REP-050") + 1), ["PROC-REP-047", "PROC-REP-211", "PROC-REP-050"]);
    // sin Detalles: el comprobante sigue a la decision de continuar con la revision (056), sin consulta por Detalle
    const v1 = orderOf(real("VAR-REP-001"));
    assert.ok(v1.indexOf("PROC-REP-056") < v1.indexOf("PROC-REP-050"), "VAR-REP-001: continuar con la revision antes del comprobante");
    assert.ok(!v1.slice(0, v1.indexOf("PROC-REP-075")).includes("PROC-REP-046"), "VAR-REP-001: ninguna consulta por Detalle antes de que existan Detalles");
    for (const id of ["HP-REP-001", "VAR-REP-001"]) {
      assert.equal(orderOf(real(id)).filter((n) => n === "PROC-REP-060").length, 1, `${id}: comprobante emitido una sola vez`);
    }
    // una autorizacion posterior (075/127/128/129/EVT-REP-003) NO regenera el comprobante: 047 -> 211 -> 080, sin pasar por 050/060
    for (const id of ["VAR-REP-001", "VAR-REP-008", "VAR-REP-010", "VAR-REP-012"]) {
      const order = orderOf(real(id));
      const last047 = order.lastIndexOf("PROC-REP-047");
      assert.deepEqual(order.slice(last047, last047 + 3), ["PROC-REP-047", "PROC-REP-211", "PROC-REP-080"], id);
      assert.ok(!order.slice(last047).includes("PROC-REP-060") && !order.slice(last047).includes("PROC-REP-050"), `${id}: la autorizacion posterior no regenera el comprobante`);
    }
    assert.ok(!traversedNodes(real("VAR-REP-007")).has("PROC-REP-060"));
    assert.match(rule("BR-REP-031"), /documento que se intercambia por el equipo fisico/);
  });

  check("revision sin Detalles: la OR espera el diagnostico sin consulta por Detalle (055 -> 056) y Recepcion consulta recien al definirse los Detalles (075 -> 046); el resolver no interviene antes", () => {
    const order = orderOf(real("VAR-REP-001"));
    assert.equal(order.filter((n) => n === "PROC-REP-046").length, 1, "una sola consulta por Detalle, despues de la definicion");
    assert.ok(order.indexOf("PROC-REP-075") < order.indexOf("PROC-REP-046") && order.indexOf("PROC-REP-046") < order.indexOf("PROC-REP-047"));
    for (const n of ["PROC-REP-211", "PROC-REP-090", "PROC-REP-129"]) {
      const at = order.indexOf(n);
      assert.ok(at === -1 || at > order.indexOf("PROC-REP-075"), `el resolver (${n}) no se invoca con cero Detalles`);
    }
    assert.ok(order.includes("PROC-REP-211"), "tras la autorizacion (con Detalles) si interviene el resolver");
    assert.equal(expectedOf(real("VAR-REP-007"), "prior_review_acceptance_authorizes_found_details"), false);
  });

  check("SIN_REPARACION (069) y la cancelacion con Detalles (BR-REP-014) siguen separados; V1.3 conserva todas las salidas de 211 salvo (d), que se bifurca por custodia", () => {
    const v13Node = new Map(v13Process.nodes.map((n) => [n.id, n]));
    assert.deepEqual(nodeById.get("PROC-REP-069"), v13Node.get("PROC-REP-069"));
    const v13Edges211 = v13Process.edges.filter((e) => e.from === "PROC-REP-211").map(key);
    const v14Edges211 = processModel.edges.filter((e) => e.from === "PROC-REP-211").map(key);
    for (const k of v13Edges211.filter((k) => !k.includes("Todos cancelados"))) assert.ok(v14Edges211.includes(k), `211 conserva ${k}`);
    assert.match(rule("BR-REP-027"), /distinta\s+de la finalizacion tecnica SIN_REPARACION/);
    assert.match(rule("BR-REP-027"), /no se ejecuta la cascada/);
    const t30 = rule("BR-REP-030");
    assert.match(t30, /COMPLETO\s+no pasan a CANCELADO/);
    assert.match(t30, /opcion\s+de UI\/UX/);
    assert.match(t30, /sin omitir las obligaciones por\s+trabajos realizados/);
  });

  check("el resto de los Scenarios es identico a V1.3 (salvo los declarados y las condiciones de origen)", () => {
    const changedIds = new Set(["HP-REP-001", "HP-REP-002", "HP-REP-003", "VAR-REP-001", "VAR-REP-002", "EXC-REP-004"]);
    const strip = (s: Scenario): unknown => {
      const copy = structuredClone(s) as Scenario;
      copy.source_process = { id: copy.source_process.id, version: "x" };
      return JSON.parse(JSON.stringify(copy).replace(/PROC-REP-090 = Ninguno trabajable/g, "PROC-REP-090 = Primera habilitacion, ninguno trabajable").replace(/"condition":"Existe Detalle trabajable"/g, '"condition":"Primera habilitacion, existe Detalle trabajable"').replace(/"condition":"Ninguno trabajable"/g, '"condition":"Primera habilitacion, ninguno trabajable"'));
    };
    for (const v13 of v13Scenarios.scenarios.filter((s) => !changedIds.has(s.id))) {
      assert.deepEqual(strip(real(v13.id)), strip(v13), v13.id);
    }
    assert.equal(scenariosModel.scenarios.length, v13Scenarios.scenarios.length + 40);
  });

  // ---------------------------------------------------------------- iteracion 5
  // Reglas internas (texto de reglas/nodos) vs escenarios que cambian el grafo (VAR-REP-004/006/007/010/011/014).
  check("[regla] bloqueo mixto: revision + autorizacion + recursos -> situacion principal REQUIERE_REVISION y las TRES causas en los bloqueos", () => {
    const t = rule("BR-REP-012");
    assert.match(t, /I\) Caso\s+mixto: DET-001 requiere revision, DET-002 esta pendiente de autorizacion\s+y DET-003 no tiene stock -> situacion principal REQUIERE_REVISION/);
    assert.match(t, /bloqueos \[REQUIERE_REVISION, PENDIENTE_AUTORIZACION, PENDIENTE_RECURSOS\]/);
    assert.match(t, /define SOLO la situacion principal y la ruta de espera\s+inicial/);
    assert.match(t, /NO descarta las\s+demas causas/);
    assert.ok(!/REQUIERE_REVISION_Y|_Y_AUTORIZACION/.test(t), "sin estados combinados");
    assert.match(nodeText("PROC-REP-211"), /conserva todas las causas\s+presentes/);
  });

  check("[regla] las causas se resuelven de forma independiente y se re-evalua tras cualquier cambio; un Detalle ejecutable deja continuar a la Orden", () => {
    const t = rule("BR-REP-012");
    assert.match(t, /se resuelven de forma independiente/);
    assert.match(t, /se vuelve a evaluar luego de cualquier\s+cambio relevante/);
    assert.match(t, /ninguna causa se pierde al resolverse otra/);
    assert.match(t, /Si\s+existe un Detalle ejecutable[^]*la Orden puede continuar con el/);
    assert.match(t, /un Detalle pendiente de\s+autorizacion nunca es ejecutable/);
    // VAR-REP-014 (grafo): al resolverse una causa el resolver se invoca de nuevo y queda la otra
    assert.equal(expectedOf(real("VAR-REP-014"), "second_resolver_situation"), "PENDIENTE_RECURSOS");
    assert.deepEqual(orderOf(real("VAR-REP-014")).slice(-3), ["PROC-REP-300", "PROC-REP-211", "PROC-REP-120"]);
  });

  check("[grafo] Orden habilitada con Detalle nuevo (VAR-REP-010): no repite 140/150/170, evalua la factibilidad del Detalle afectado y vuelve al resolver con el hito historico", () => {
    const o = orderOf(real("VAR-REP-010"));
    for (const n of ["PROC-REP-140", "PROC-REP-150", "PROC-REP-170"]) assert.ok(!o.includes(n), `no repite ${n}`);
    assert.ok(o.indexOf("PROC-REP-211") < o.indexOf("PROC-REP-080"), "el resolver enruta la autorizacion a factibilidad");
    assert.ok(o.indexOf("PROC-REP-080") < o.indexOf("PROC-REP-090") && o.indexOf("PROC-REP-090") < o.lastIndexOf("PROC-REP-211"));
    assert.match(nodeText("PROC-REP-090"), /HITO\s+historico de habilitacion, no el estado agregado actual/);
    assert.match(nodeText("PROC-REP-090"), /tres salidas son\s+mutuamente excluyentes y completas/);
    assert.match(rule("BR-REP-034"), /"Orden ya habilitada" se determina por el HITO\s+historico de habilitacion/);
    assert.match(rule("BR-REP-034"), /se ejecuta una unica vez/);
    // 090 conserva sus aristas de V1.3 para la primera habilitacion
    const v13e = v13Process.edges.filter((e) => e.from === "PROC-REP-090").map(key);
    const v14e = processModel.edges.filter((e) => e.from === "PROC-REP-090").map(key);
    for (const k of v13e) {
      const renamed = k.replace("::Existe Detalle", "::Primera habilitacion, existe Detalle").replace("::Ninguno trabajable", "::Primera habilitacion, ninguno trabajable");
      assert.ok(v14e.includes(renamed), `090 conserva (renombrada) ${k}`);
    }
    // tambien tras una revalidacion de recursos/redefinicion (VAR-REP-013): sin 140/150
    const late = orderOf(real("VAR-REP-013"));
    assert.ok(!late.includes("PROC-REP-140") && !late.includes("PROC-REP-150"));
  });

  check("[regla] la prioridad de cola se conserva; solo cambia por una accion explicita y autorizada con trazabilidad, sin proceso nuevo ni reenvio a 150", () => {
    const t = rule("BR-REP-034");
    assert.match(t, /no se crea otra entrada en la cola, no se solicita prioridad\s+automaticamente/);
    assert.match(t, /la prioridad existente se mantiene al agregar o\s+modificar un Detalle/);
    assert.match(t, /accion explicita y autorizada,\s+con trazabilidad/);
    assert.match(t, /sin crear un nuevo proceso de\s+priorizacion/);
    assert.match(t, /ninguna reevaluacion reenvia la Orden a PROC-REP-150/);
    assert.match(nodeText("PROC-REP-150"), /NO vuelve aqui ni modifica la prioridad existente/);
    // la unica arista hacia 150 sigue siendo la de primera habilitacion (140 -> 150), igual que en V1.3
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-150").map((e) => e.from), ["PROC-REP-140"]);
    assert.deepEqual(v13Process.edges.filter((e) => e.to === "PROC-REP-150").map((e) => e.from), ["PROC-REP-140"]);
  });

  check("[regla/grafo] la toma activa se conserva al agregar un Detalle y en los retornos 080/090/211: sin liberar, duplicar ni interrumpir otra Ejecucion", () => {
    const t = rule("BR-REP-034");
    assert.match(t, /no libera la toma activa del tecnico, no sobrescribe su\s+historial, no interrumpe la Ejecucion de otro Detalle \(BR-REP-007\) ni\s+duplica la toma/);
    assert.match(t, /el Detalle nuevo no puede iniciarse hasta estar\s+autorizado y ser factible/);
    assert.match(nodeText("PROC-REP-128"), /este nodo no cierra la toma ni toca la Ejecucion vigente/);
    assert.match(nodeText("PROC-REP-211"), /NO libera ni duplica la toma activa ni toca la prioridad de\s+cola/);
    for (const id of ["VAR-REP-010", "VAR-REP-011"]) {
      const nodes = traversedNodes(real(id));
      for (const n of ["PROC-REP-180", "PROC-REP-212", "PROC-REP-170", "PROC-REP-200", "PROC-REP-210"]) {
        assert.ok(!nodes.has(n), `${id} no pasa por ${n}`);
      }
      assert.equal(orderOf(real(id)).at(-1), "PROC-REP-190");
    }
  });

  check("[grafo] DET-001 sigue EN_PROGRESO mientras DET-002 espera; autorizar (VAR-REP-010) o rechazar (VAR-REP-011) DET-002 no interrumpe DET-001", () => {
    for (const id of ["VAR-REP-010", "VAR-REP-011"]) {
      assert.equal(expectedOf(real(id), "active_execution_interrupted"), false, id);
      assert.equal(factOf(real(id), "active_execution_on_other_detail"), true, id);
      assert.equal(orderOf(real(id))[0], "EVT-REP-003", id);
      assert.deepEqual(orderOf(real(id)).slice(-2), ["PROC-REP-211", "PROC-REP-190"], id);
    }
    assert.equal(expectedOf(real("VAR-REP-010"), "new_detail_startable_before_feasibility"), false);
    assert.ok(orderOf(real("VAR-REP-010")).includes("PROC-REP-080"), "DET-002 requiere factibilidad antes de iniciarse");
    assert.ok(!orderOf(real("VAR-REP-011")).includes("PROC-REP-080"));
    assert.match(rule("BR-REP-034"), /Concurrencia: la consulta al cliente por un Detalle nuevo/);
    assert.match(rule("BR-REP-032"), /concurrente con la ejecucion de otro Detalle/);
    assert.match(nodeText("PROC-REP-190"), /Limitacion de representacion: el\s+grafo es secuencial/);
    assert.match(nodeText("PROC-REP-128"), /concurrente con la ejecucion de otro Detalle/);
    assert.match(nodeText("PROC-REP-047"), /autorizar o rechazar NO interrumpe la Ejecucion de otro/);
    // sin nodos de paralelismo
    assert.ok(!processModel.nodes.some((n) => /PARALEL|FORK|JOIN/i.test(n.id + n.name)));
  });

  check("[regla] custodia: generar el comprobante (060) no confirma el intercambio fisico; la Orden puede existir sin equipo recibido", () => {
    const c = rule("BR-REP-033");
    assert.match(c, /su GENERACION \(PROC-REP-060\) no equivale al\s+intercambio fisico/);
    assert.match(c, /la custodia comienza cuando se CONFIRMA el\s+intercambio/);
    assert.match(c, /La Orden puede existir sin equipo recibido/);
    assert.match(c, /un\s+comprobante generado pero no entregado no activa la custodia/);
    assert.match(c, /SIN CUSTODIA[^]*EQUIPO\s+BAJO CUSTODIA[^]*EQUIPO YA DEVUELTO[^]*FISICA SIN CONFIRMAR/);
    const n = nodeText("PROC-REP-060");
    assert.match(n, /GENERARLO no confirma el intercambio fisico/);
    assert.match(n, /no activa la custodia ni se interpreta como\s+equipo recibido o no recibido/);
    assert.match(n, /se extiende este nodo en\s+lugar de agregar un nodo posterior/);
    assert.match(rule("BR-REP-031"), /su generacion no confirma\s+por si sola el intercambio fisico/);
  });

  check("[regla] comprobante entregado + recepcion fisica confirmada: registra fecha/hora, usuario responsable y referencia del comprobante", () => {
    const c = rule("BR-REP-033");
    assert.match(c, /fecha\/hora,\s+usuario responsable y referencia del comprobante de recepcion/);
    const outs = (nodeById.get("PROC-REP-060") as unknown as { outputs?: string[] }).outputs ?? [];
    assert.ok(outs.some((o) => /Confirmacion del intercambio fisico \(fecha\/hora, usuario responsable y referencia del comprobante\)/.test(o)));
    assert.ok(outs.some((o) => /Comprobante de recepcion generado/.test(o)));
    assert.match(nodeText("PROC-REP-211"), /custodia CONFIRMADA/);
    assert.match(nodeText("PROC-REP-306"), /CONFIRMADA \(comprobante entregado a cambio del equipo, no simplemente\s+generado/);
    assert.match(c, /NO se envia automaticamente\s+a devolucion un equipo cuya recepcion no esta confirmada/);
  });

  check("[grafo] cancelacion: sin recepcion confirmada no hay devolucion (VAR-REP-004/006); con custodia confirmada la devolucion es obligatoria antes del fin (VAR-REP-007)", () => {
    for (const id of ["VAR-REP-004", "VAR-REP-006"]) {
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-270"), id);
      assert.equal(expectedOf(real(id), "equipment_return_registered"), false, id);
    }
    const o7 = orderOf(real("VAR-REP-007"));
    assert.deepEqual(o7.slice(-4), ["PROC-REP-211", "PROC-REP-270", "PROC-REP-268", "EVT-REP-999"]);
    assert.equal(expectedOf(real("VAR-REP-007"), "equipment_return_registered"), true);
    assert.match(rule("BR-REP-033"), /Equipo nunca recibido \(1\): no requiere\s+devolucion/);
    assert.match(rule("BR-REP-033"), /puede finalizar operativamente mientras no este determinada/);
    assert.match(nodeText("PROC-REP-270"), /recepcion\s+fisica confirmada/);
  });

  check("[grafo] la devolucion no convierte CANCELADA en ENTREGADA; los otros origenes conservan su custodia sin definir", () => {
    assert.equal(expectedOf(real("VAR-REP-007"), "marked_delivered"), false);
    assert.match(rule("BR-REP-033"), /no convierte CANCELADA en ENTREGADA \(la Orden\s+permanece CANCELADA\)/);
    for (const bad of ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-280"]) {
      assert.ok(!traversedNodes(real("VAR-REP-007")).has(bad), bad);
    }
    assert.match(rule("BR-REP-033"), /RT_INTERNO \(no emite comprobante de\s+recepcion\)[^]*no estan definidas todavia y se conservan sin cambios/);
    for (const n of ["PROC-REP-127", "PROC-REP-128"]) {
      assert.ok(outgoing(n).some((e) => e.endsWith("->PROC-REP-080")), `${n} -> 080 para los otros origenes`);
    }
    assert.match(nodeText("PROC-REP-270"), /Para RT_INTERNO/);
  });

  // ---------------------------------------------------------------- correcciones finales: custodia pendiente y salidas de 090
  check("custodia desconocida: toda cancelacion con recepcion sin confirmar pasa por 271 y no alcanza FIN ni 270 de forma directa (VAR-REP-015)", () => {
    for (const from of ["PROC-REP-211", "PROC-REP-306"]) {
      const outs = processModel.edges.filter((e) => e.from === from);
      const unk = outs.filter((e) => e.to === "PROC-REP-271");
      assert.equal(unk.length, 1, `${from} -> 271`);
      assert.match(unk[0].condition ?? "", /custodia sin confirmar/i);
      // ninguna otra salida de cancelacion es compatible con la custodia desconocida
      for (const e of outs.filter((e) => e.to === "PROC-REP-268" || e.to === "PROC-REP-270")) {
        assert.doesNotMatch(e.condition ?? "", /sin confirmar/i);
      }
    }
    assert.deepEqual(outgoing("PROC-REP-271"), ["Equipo bajo custodia->PROC-REP-270", "Sin equipo bajo custodia->PROC-REP-268"].sort());
    const o = orderOf(real("VAR-REP-015"));
    assert.deepEqual(o, ["PROC-REP-211", "PROC-REP-271", "PROC-REP-270", "PROC-REP-268", "EVT-REP-999"]);
    assert.ok(o.indexOf("PROC-REP-271") < o.indexOf("EVT-REP-999"), "271 antes del fin");
    assert.equal(expectedOf(real("VAR-REP-015"), "operational_end_before_custody_resolved"), false);
    assert.equal(expectedOf(real("VAR-REP-015"), "automatic_return_of_unconfirmed_equipment"), false);
    assert.equal(expectedOf(real("VAR-REP-015"), "marked_delivered"), false);
    const n = nodeText("PROC-REP-271");
    assert.match(n, /NO finaliza operativamente hasta resolver la custodia/);
    assert.match(n, /NO se envia automaticamente a devolucion/);
    assert.match(n, /usuario, fecha\/hora y evidencia o\s+referencia/);
    assert.equal(nodeById.get("PROC-REP-271")?.actor, "ACT-RECEP");
  });

  check("custodia: equipo nunca recibido no exige devolucion; equipo ya devuelto no duplica la devolucion; las tres salidas de 211/306 son excluyentes", () => {
    for (const id of ["VAR-REP-004", "VAR-REP-006"]) assert.ok(!traversedNodes(real(id)).has("PROC-REP-270"), id);
    const c = rule("BR-REP-033");
    assert.match(c, /Equipo ya devuelto \(3\): no se duplica la\s+devolucion/);
    assert.match(c, /mutuamente excluyentes\s+y completas/);
    assert.match(nodeText("PROC-REP-271"), /recibido y ya devuelto -> fin, sin duplicar la devolucion/);
    assert.match(nodeText("PROC-REP-270"), /no se registra una segunda\s+devolucion/);
    // 270 solo es alcanzable desde 211, 306 y 271 (la cancelacion), ademas de los contextos previos
    assert.ok(processModel.edges.filter((e) => e.to === "PROC-REP-270").map((e) => e.from).includes("PROC-REP-271"));
    // la devolucion no pasa por entrega comercial
    for (const bad of ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-280", "PROC-REP-220"]) {
      assert.ok(!reachableInContext("PROC-REP-271").includes(bad), bad);
    }
  });

  check("PROC-REP-090: salidas mutuamente excluyentes y completas por hito historico; una OR ya habilitada no vuelve a 140/150", () => {
    assert.deepEqual(outgoing("PROC-REP-090"), [
      "Orden ya habilitada->PROC-REP-211",
      "Primera habilitacion, existe Detalle trabajable->PROC-REP-140",
      "Primera habilitacion, ninguno trabajable->PROC-REP-100",
    ].sort());
    const conds = processModel.edges.filter((e) => e.from === "PROC-REP-090").map((e) => e.condition);
    assert.equal(new Set(conds).size, conds.length, "condiciones distintas");
    assert.ok(conds.every((c) => c && c.length > 0), "todas condicionadas");
    assert.match(rule("BR-REP-034"), /mutuamente excluyentes y completas, sin depender del orden de las\s+aristas/);
    // la unica arista hacia 150 sigue siendo 140 -> 150 y las rutas de V1.3 de primera habilitacion se conservan
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-150").map((e) => e.from), ["PROC-REP-140"]);
    for (const id of ["HP-REP-001", "HP-REP-002", "HP-REP-003"]) {
      const o = orderOf(real(id));
      assert.ok(o.includes("PROC-REP-140") && o.includes("PROC-REP-150"), `${id} conserva 090 -> 140 -> 150`);
    }
    for (const id of ["VAR-REP-010", "VAR-REP-013"]) {
      const o = orderOf(real(id));
      assert.ok(!o.includes("PROC-REP-140") && !o.includes("PROC-REP-150"), `${id} no repite 140/150`);
    }
  });

  // ---------------------------------------------------------------- evaluacion tecnica previa a la ejecucion: aplicacion inmediata del resultado principal y reparaciones adicionales
  check("[grafo] 182/183/184: el resultado principal se aplica de inmediato (183 -> 184/300/127) y las altas son complementarias; todo camino a PROC-REP-185 pasa por PROC-REP-182", () => {
    assert.deepEqual(outgoing("PROC-REP-182"), ["No requiere evaluacion tecnica->PROC-REP-174", "Requiere evaluacion tecnica->PROC-REP-183"].sort());
    // exactamente tres resultados principales; ninguna salida de 183 va a 128 (el alta no es un resultado)
    assert.deepEqual(outgoing("PROC-REP-183"), [
      "CONFIRMADO->PROC-REP-184",
      "DESCARTADO->PROC-REP-300",
      "REQUIERE_REDEFINICION->PROC-REP-127",
    ].sort());
    // el efecto de 300/127 en la evaluacion no queda detras de la consulta al cliente: vuelven a 184, no a 046/211
    assert.deepEqual(outgoing("PROC-REP-300"), ["Cancelacion fuera de la evaluacion tecnica->PROC-REP-211", "Descarte durante la evaluacion tecnica->PROC-REP-184"].sort());
    assert.deepEqual(outgoing("PROC-REP-127"), [
      "Redefinicion durante la evaluacion tecnica->PROC-REP-184",
      "Redefinicion posterior a una Ejecucion, CLIENTE_EXTERNO->PROC-REP-046",
      `Redefinicion posterior a una Ejecucion, ${OTHER.replace("Origen", "origen")}->PROC-REP-080`,
    ].sort());
    assert.deepEqual(outgoing("PROC-REP-184"), [
      "Otra reparacion adicional por registrar->PROC-REP-128",
      "Hay Detalles pendientes de factibilidad (origen distinto de CLIENTE_EXTERNO)->PROC-REP-080",
      "Original CONFIRMADO, sin Detalles pendientes de factibilidad->PROC-REP-182",
      "Original cancelado o redefinido, sin Detalles pendientes de factibilidad->PROC-REP-211",
    ].sort());
    assert.ok(outgoing("PROC-REP-128").includes("Alta durante la evaluacion tecnica->PROC-REP-184"));
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-184").map((e) => e.from).sort(), ["PROC-REP-127", "PROC-REP-128", "PROC-REP-183", "PROC-REP-300"]);
    // condiciones distintas (excluyentes) en cada nodo bifurcado
    for (const n of ["PROC-REP-182", "PROC-REP-183", "PROC-REP-184", "PROC-REP-300", "PROC-REP-127", "PROC-REP-128"]) {
      const conds = processModel.edges.filter((e) => e.from === n).map((e) => e.condition);
      assert.ok(conds.every((c) => c && c.length > 0), `${n}: todas condicionadas`);
      assert.equal(new Set(conds).size, conds.length, `${n}: condiciones distintas`);
    }
    // 174 solo se alcanza desde 182, y 183 solo desde 182: no hay camino a 185 sin evaluacion vigente
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-174").map((e) => e.from), ["PROC-REP-182"]);
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-183").map((e) => `${e.from}:${e.condition}`), ["PROC-REP-182:Requiere evaluacion tecnica"]);
    assert.ok(!processModel.edges.some((e) => e.from === "PROC-REP-181" && e.to !== "PROC-REP-182"), "181 solo conduce a 182");
    const incoming = new Set(processModel.edges.map((e) => e.to));
    const roots = processModel.nodes.map((n) => n.id).filter((id) => !incoming.has(id));
    const seen = new Set<string>(roots);
    const queue = [...roots];
    while (queue.length) {
      const cur = queue.shift() as string;
      for (const e of processModel.edges.filter((x) => x.from === cur)) {
        if (e.to === "PROC-REP-182" || seen.has(e.to)) continue;
        seen.add(e.to);
        queue.push(e.to);
      }
    }
    assert.ok(!seen.has("PROC-REP-185"), "ningun camino a 185 evita 182");
    assert.equal(nodeById.get("PROC-REP-184")?.type, "decision");
    assert.match(nodeText("PROC-REP-183"), /EXACTAMENTE UN resultado principal/);
    assert.match(nodeText("PROC-REP-183"), /se aplica de INMEDIATO sobre el Detalle original, sin esperar a\s+que se registren, consulten o evaluen las reparaciones adicionales/);
    assert.match(nodeText("PROC-REP-183"), /NO es un resultado de esta evaluacion ni una alternativa a ella/);
    assert.match(nodeText("PROC-REP-184"), /cada alta es un Detalle distinto, nunca una\s+nueva evaluacion del Detalle original/);
    assert.match(nodeText("PROC-REP-184"), /Solo asi se invoca el resolver despues de un descarte/);
    assert.match(nodeText("PROC-REP-300"), /"Descarte durante la evaluacion tecnica" ->\s+PROC-REP-184/);
  });

  check("[responsabilidades] ACT-TECH define 075, redefine 127, agrega 128 y evalua 183; ACT-RECEP conserva 070 y la consulta/autorizacion 046/047", () => {
    for (const id of ["PROC-REP-065", "PROC-REP-075", "PROC-REP-126", "PROC-REP-127", "PROC-REP-128", "PROC-REP-183"]) assert.equal(nodeById.get(id)?.actor, "ACT-TECH", id);
    for (const id of ["PROC-REP-046", "PROC-REP-070"]) assert.equal(nodeById.get(id)?.actor, "ACT-RECEP", id);
    const v13 = (id: string) => v13Process.nodes.find((n) => n.id === id);
    assert.equal(nodeById.get("PROC-REP-070")?.actor, v13("PROC-REP-070")?.actor, "070 conserva su actor de V1.3");
    assert.equal(v13("PROC-REP-075")?.actor, "ACT-RECEP", "en V1.3 075 era de Recepcion");
    // caminos entrantes a 075 y a 127: todos con actor tecnico (o decision sin actor)
    for (const target of ["PROC-REP-075", "PROC-REP-127"]) {
      for (const from of processModel.edges.filter((e) => e.to === target).map((e) => e.from)) {
        const actor = nodeById.get(from)?.actor;
        assert.ok(actor === undefined || actor === "ACT-TECH", `${from} (${actor}) -> ${target}`);
      }
    }
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-075").map((e) => e.from), ["PROC-REP-068"]);
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-127").map((e) => e.from).sort(), ["PROC-REP-126", "PROC-REP-183"]);
    // la consulta y la autorizacion siguen siendo de Recepcion; 075 conserva sus salidas hacia 046/080
    assert.ok(outgoing("PROC-REP-075").includes("CLIENTE_EXTERNO->PROC-REP-046"));
    assert.ok(outgoing("PROC-REP-075").includes(`${OTHER}->PROC-REP-080`));
    const d75 = nodeText("PROC-REP-075");
    assert.match(d75, /el TECNICO \(ACT-TECH\) define y registra los Detalles de\s+Reparacion requeridos/);
    assert.match(d75, /PROC-REP-070, que sigue a cargo de Recepcion\s+como definicion preliminar/);
    assert.match(d75, /el\s+tecnico que lo definio, la fecha\/hora y la referencia a la revision\s+inicial \(PROC-REP-065\)/);
    assert.match(d75, /Definir tecnicamente un Detalle NO\s+es autorizarlo/);
    assert.match(d75, /REVISION_TECNICA/);
    assert.match(d75, /NO requieren una segunda confirmacion tecnica\s+independiente/);
    assert.match(d75, /BR-REP-015/);
    assert.match(d75, /BR-REP-019/);
    assert.ok(((nodeById.get("PROC-REP-075") as unknown as { outputs?: string[] }).outputs ?? []).some((o) => /tecnico que lo definio, fecha\/hora y referencia a la revision inicial \(PROC-REP-065\)/.test(o)));
    assert.deepEqual((nodeById.get("PROC-REP-075") as unknown as { rules?: string[] }).rules, ["BR-REP-001", "BR-REP-019"], "075 conserva sus reglas");
    assert.match(rule("BR-REP-019"), /tras la revision, el tecnico define\s+y registra uno o mas Detalles nuevos \(PROC-REP-075\)/);
    const d127 = nodeText("PROC-REP-127");
    assert.match(d127, /quien\s+registra la redefinicion es el TECNICO \(ACT-TECH\)/);
    assert.match(d127, /Recepcion NO registra redefiniciones tecnicas/);
    assert.match(d127, /conserva la definicion\s+preliminar inicial \(PROC-REP-070\)/);
    assert.match(d127, /conserva\s+historicamente la definicion anterior/);
    assert.match(d127, /vinculo al Detalle\s+origen y a la Orden origen/);
    assert.match(d127, /invalida la autorizacion del cliente de la\s+definicion anterior/);
    assert.match(d127, /obliga a reevaluar los recursos desde cero/);
    assert.match(d127, /vuelve a PROC-REP-046 para una nueva decision antes de\s+PROC-REP-080/);
    assert.match(nodeText("PROC-REP-128"), /el tecnico es\s+el responsable de definir tecnicamente este trabajo, no Recepcion/);
    assert.match(nodeText("PROC-REP-128"), /Registrar un Detalle nuevo NO invalida la autorizacion ni la\s+definicion del Detalle original/);
    assert.match(nodeText("PROC-REP-046"), /Es el unico punto donde Recepcion registra la autorizacion o el desistimiento/);
    const f2 = featuresModel.features.find((x) => x.id === "FEAT-REP-002");
    assert.match(JSON.stringify(f2), /PROC-REP-075, PROC-REP-127 y\s+PROC-REP-128 son del tecnico/);
    // 125/126 siguen identicos a V1.3 (redefinicion posterior a una Ejecucion interrumpida)
    for (const id of ["PROC-REP-125", "PROC-REP-126"]) assert.deepEqual(nodeById.get(id), v13(id), id);
    // los Happy Paths que pasan por 075 (HP-REP-003) conservan su recorrido 065 -> 068 -> 075
    const o3 = orderOf(real("HP-REP-003"));
    assert.ok(o3.indexOf("PROC-REP-065") < o3.indexOf("PROC-REP-068") && o3.indexOf("PROC-REP-068") < o3.indexOf("PROC-REP-075"));
  });

  check("VAR-REP-016, 021 y Happy Paths: confirmacion tecnica de un Detalle de Recepcion; un Detalle REVISION_TECNICA (075/128) no requiere segunda confirmacion", () => {
    const o16 = orderOf(real("VAR-REP-016"));
    assert.deepEqual(o16, ["PROC-REP-181", "PROC-REP-182", "PROC-REP-183", "PROC-REP-184", "PROC-REP-182", "PROC-REP-174", "PROC-REP-185", "PROC-REP-190"]);
    assert.equal(o16.filter((n) => n === "PROC-REP-183").length, 1, "el resultado principal se registra una sola vez");
    assert.ok(o16.indexOf("PROC-REP-183") < o16.indexOf("PROC-REP-185"), "confirmacion antes de la reserva");
    assert.equal(factOf(real("VAR-REP-016"), "detail_diagnosis_origin"), "RECEPCION");
    assert.equal(factOf(real("VAR-REP-016"), "principal_result"), "CONFIRMADO");
    assert.equal(expectedOf(real("VAR-REP-016"), "customer_authorization_kept"), true);
    assert.equal(expectedOf(real("VAR-REP-016"), "customer_authorization_requested_again"), false);
    assert.equal(expectedOf(real("VAR-REP-016"), "new_definition_created"), false);
    assert.equal(expectedOf(real("VAR-REP-016"), "inventory_reserved_during_evaluation"), false);
    const o21 = orderOf(real("VAR-REP-021"));
    assert.ok(!o21.includes("PROC-REP-183") && !o21.includes("PROC-REP-184"));
    assert.equal(factOf(real("VAR-REP-021"), "detail_diagnosis_origin"), "REVISION_TECNICA");
    assert.equal(expectedOf(real("VAR-REP-021"), "technical_evaluation_required"), false);
    assert.equal(expectedOf(real("VAR-REP-021"), "customer_authorization_still_required_when_applicable"), true);
    assert.equal(expectedOf(real("VAR-REP-021"), "feasibility_still_required"), true);
    for (const id of ["HP-REP-001", "HP-REP-002"]) {
      const o = orderOf(real(id));
      assert.ok(o.includes("PROC-REP-183") && o.includes("PROC-REP-184"), id);
      assert.equal(o.filter((n) => n === "PROC-REP-183").length, 1, `${id} evalua una sola vez`);
      assert.ok(o.indexOf("PROC-REP-183") < o.indexOf("PROC-REP-184") && o.indexOf("PROC-REP-184") < o.indexOf("PROC-REP-185"), id);
    }
    // origen REVISION_TECNICA definido por 075 (HP-REP-003): sin 183/184
    const o3 = orderOf(real("HP-REP-003"));
    assert.ok(o3.includes("PROC-REP-075") && !o3.includes("PROC-REP-183") && !o3.includes("PROC-REP-184"));
  });

  check("VAR-REP-017/018: DESCARTADO se aplica de inmediato (183 -> 300 -> 184), el Detalle descartado no puede ejecutarse y sin adicionales el resolver recien interviene despues", () => {
    const o17 = orderOf(real("VAR-REP-017"));
    assert.deepEqual(o17, ["PROC-REP-183", "PROC-REP-300", "PROC-REP-184", "PROC-REP-211"]);
    assert.equal(factOf(real("VAR-REP-017"), "principal_result"), "DESCARTADO");
    assert.equal(expectedOf(real("VAR-REP-017"), "cancellation_reason"), "DIAGNOSTICO_DESCARTADO");
    assert.equal(expectedOf(real("VAR-REP-017"), "effect_applied_immediately"), true);
    assert.equal(expectedOf(real("VAR-REP-017"), "discarded_detail_selectable_for_execution"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "recorded_as_customer_desistment"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "other_details_cancelled"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "order_cancelled"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "take_released"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "inventory_reserved_or_consumed"), false);
    assert.equal(expectedOf(real("VAR-REP-017"), "duplicate_cancellation"), false);
    for (const id of ["VAR-REP-017", "VAR-REP-018", "VAR-REP-023", "VAR-REP-024"]) {
      const nodes = traversedNodes(real(id));
      for (const bad of ["PROC-REP-174", "PROC-REP-185", "PROC-REP-190", "PROC-REP-181"]) assert.ok(!nodes.has(bad), `${id}: el Detalle descartado no llega a ${bad}`);
      assert.ok(!nodes.has("PROC-REP-305") && !nodes.has("PROC-REP-306") && (id === "VAR-REP-024" || !nodes.has("PROC-REP-047")), `${id}: no es desistimiento del cliente`);
      assert.equal(orderOf(real(id)).filter((n) => n === "PROC-REP-300").length, 1, `${id}: una sola cancelacion`);
    }
    assert.deepEqual(orderOf(real("VAR-REP-018")), ["PROC-REP-183", "PROC-REP-300", "PROC-REP-184", "PROC-REP-211", "PROC-REP-270", "PROC-REP-268", "EVT-REP-999"]);
    assert.equal(expectedOf(real("VAR-REP-018"), "marked_delivered"), false);
    assert.equal(expectedOf(real("VAR-REP-018"), "equipment_return_registered"), true);
    assert.match(nodeText("PROC-REP-300"), /DIAGNOSTICO_DESCARTADO/);
  });

  check("VAR-REP-019: REQUIERE_REDEFINICION se aplica de inmediato (183 -> 127 -> 184); el tecnico registra y la nueva autorizacion queda pendiente para Recepcion sin que el tecnico la espere", () => {
    const o19 = orderOf(real("VAR-REP-019"));
    assert.deepEqual(o19, ["PROC-REP-183", "PROC-REP-127", "PROC-REP-184", "PROC-REP-211", "PROC-REP-129"]);
    for (const n of ["PROC-REP-125", "PROC-REP-126", "PROC-REP-140", "PROC-REP-150", "PROC-REP-174", "PROC-REP-185", "PROC-REP-046", "PROC-REP-047"]) assert.ok(!o19.includes(n), `VAR-REP-019 no recorre ${n}`);
    assert.equal(factOf(real("VAR-REP-019"), "principal_result"), "REQUIERE_REDEFINICION");
    assert.equal(expectedOf(real("VAR-REP-019"), "redefinition_registered_by"), "ACT-TECH");
    assert.equal(expectedOf(real("VAR-REP-019"), "effect_applied_immediately"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "previous_definition_executable"), false);
    assert.equal(expectedOf(real("VAR-REP-019"), "same_detail_preserved"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "previous_definition_preserved"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "previous_authorization_invalidated"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "new_customer_authorization_requested"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "technical_thread_waits_for_customer"), false);
    assert.equal(expectedOf(real("VAR-REP-019"), "feasibility_reevaluated_after_authorization"), true);
    assert.equal(expectedOf(real("VAR-REP-019"), "redundant_technical_confirmation_required"), false);
    assert.equal(expectedOf(real("VAR-REP-019"), "inventory_reserved_on_invalidated_definition"), false);
  });

  check("VAR-REP-020/022/023/024/025: casos A, B y C; el efecto del resultado principal precede a las altas; el hilo tecnico nunca recorre la consulta al cliente; la Orden no finaliza prematuramente", () => {
    // Caso A: CONFIRMADO + adicional pendiente de autorizacion sin respuesta del cliente
    const o20 = orderOf(real("VAR-REP-020"));
    assert.deepEqual(o20, ["PROC-REP-183", "PROC-REP-184", "PROC-REP-128", "PROC-REP-184", "PROC-REP-182", "PROC-REP-174", "PROC-REP-185", "PROC-REP-190"]);
    assert.equal(o20.filter((n) => n === "PROC-REP-183").length, 1, "evaluacion del original una sola vez");
    assert.ok(!o20.includes("PROC-REP-046") && !o20.includes("PROC-REP-047"), "DET-001 continua hacia ejecucion sin pasar por la consulta");
    assert.equal(factOf(real("VAR-REP-020"), "principal_result"), "CONFIRMADO");
    assert.equal(factOf(real("VAR-REP-020"), "additional_details_count"), 1);
    assert.equal(factOf(real("VAR-REP-020"), "new_detail_diagnosis_origin"), "REVISION_TECNICA");
    assert.equal(factOf(real("VAR-REP-020"), "new_detail_initial_authorization"), "PENDIENTE_AUTORIZACION");
    assert.equal(factOf(real("VAR-REP-020"), "customer_response"), "SIN_RESPUESTA");
    assert.equal(expectedOf(real("VAR-REP-020"), "additional_detail_registered_by"), "ACT-TECH");
    assert.equal(expectedOf(real("VAR-REP-020"), "authorization_request_created_by"), "ACT-TECH");
    assert.equal(expectedOf(real("VAR-REP-020"), "authorization_request_resolved_by"), "ACT-RECEP");
    assert.equal(expectedOf(real("VAR-REP-020"), "technical_thread_waits_for_customer"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "additional_detail_authorization_state"), "PENDIENTE_AUTORIZACION");
    assert.equal(expectedOf(real("VAR-REP-020"), "original_result_replaced_by_additional"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "original_detail_modified"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "original_authorization_kept"), true);
    assert.equal(expectedOf(real("VAR-REP-020"), "original_blocked_by_additional_decision"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "original_reevaluated_or_duplicated"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "new_detail_requires_second_technical_confirmation"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "new_detail_startable_before_authorization"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "inventory_reserved_for_additional"), false);
    assert.equal(expectedOf(real("VAR-REP-020"), "order_goes_to_technical_control"), false);
    assert.ok(!o20.includes("PROC-REP-300") && !o20.includes("PROC-REP-127"), "detectar un trabajo adicional no descarta ni redefine el original");
    assert.ok(!o20.includes("PROC-REP-140") && !o20.includes("PROC-REP-150") && !o20.includes("PROC-REP-170"));
    const o22 = orderOf(real("VAR-REP-022"));
    assert.equal(o22.filter((n) => n === "PROC-REP-128").length, 2, "dos altas");
    assert.equal(o22.filter((n) => n === "PROC-REP-183").length, 1, "una sola evaluacion del original");
    assert.ok(!o22.includes("PROC-REP-046") && o22.at(-1) === "PROC-REP-190", "el original llega a ejecucion sin consulta");
    assert.equal(factOf(real("VAR-REP-022"), "additional_details_count"), 2);
    assert.equal(expectedOf(real("VAR-REP-022"), "each_additional_detail_has_own_authorization"), true);
    assert.equal(expectedOf(real("VAR-REP-022"), "each_additional_detail_has_own_feasibility"), true);
    assert.equal(expectedOf(real("VAR-REP-022"), "active_take_and_priority_kept"), true);
    // Caso B: DESCARTADO + adicional (otro origen) y unico Detalle descartado (CLIENTE_EXTERNO)
    const o23 = orderOf(real("VAR-REP-023"));
    assert.deepEqual(o23, ["PROC-REP-183", "PROC-REP-300", "PROC-REP-184", "PROC-REP-128", "PROC-REP-184", "PROC-REP-080", "PROC-REP-090", "PROC-REP-211"]);
    assert.ok(!o23.includes("PROC-REP-046") && !o23.includes("PROC-REP-047"));
    assert.ok(o23.indexOf("PROC-REP-300") < o23.indexOf("PROC-REP-128"), "el descarte se aplica antes del alta");
    assert.equal(factOf(real("VAR-REP-023"), "principal_result"), "DESCARTADO");
    assert.equal(expectedOf(real("VAR-REP-023"), "effect_applied_immediately"), true);
    assert.equal(expectedOf(real("VAR-REP-023"), "customer_consultation_required"), false);
    const o24 = orderOf(real("VAR-REP-024"));
    assert.deepEqual(o24, ["PROC-REP-183", "PROC-REP-300", "PROC-REP-184", "PROC-REP-128", "PROC-REP-184", "PROC-REP-211", "PROC-REP-129"]);
    assert.ok(o24.indexOf("PROC-REP-300") < o24.indexOf("PROC-REP-128") && o24.indexOf("PROC-REP-128") < o24.indexOf("PROC-REP-211"), "descarte, luego alta, luego resolver");
    assert.ok(!o24.includes("PROC-REP-046") && !o24.includes("PROC-REP-047"), "el hilo tecnico no recorre la consulta");
    assert.equal(factOf(real("VAR-REP-024"), "original_was_only_detail"), true);
    assert.equal(expectedOf(real("VAR-REP-024"), "order_finalized_prematurely"), false);
    assert.equal(expectedOf(real("VAR-REP-024"), "custody_return_triggered_prematurely"), false);
    assert.equal(expectedOf(real("VAR-REP-024"), "resolver_invoked_before_additional_registered"), false);
    assert.equal(expectedOf(real("VAR-REP-024"), "order_waits_for"), "AUTORIZACION_DEL_ADICIONAL");
    for (const bad of ["PROC-REP-270", "PROC-REP-271", "EVT-REP-999", "PROC-REP-306", "PROC-REP-220"]) assert.ok(!traversedNodes(real("VAR-REP-024")).has(bad), `VAR-REP-024 no recorre ${bad}`);
    // Caso C: REQUIERE_REDEFINICION + adicional
    const o25 = orderOf(real("VAR-REP-025"));
    assert.deepEqual(o25, ["PROC-REP-183", "PROC-REP-127", "PROC-REP-184", "PROC-REP-128", "PROC-REP-184", "PROC-REP-211", "PROC-REP-129"]);
    assert.ok(o25.indexOf("PROC-REP-127") < o25.indexOf("PROC-REP-128") && o25.indexOf("PROC-REP-128") < o25.indexOf("PROC-REP-211"), "redefinicion, luego alta, luego resolver");
    assert.equal(o25.filter((n) => n === "PROC-REP-127").length, 1, "una sola redefinicion");
    assert.equal(expectedOf(real("VAR-REP-025"), "redefinition_registered_by"), "ACT-TECH");
    assert.equal(expectedOf(real("VAR-REP-025"), "previous_definition_executable"), false);
    assert.equal(expectedOf(real("VAR-REP-025"), "each_detail_has_own_authorization_and_feasibility"), true);
    assert.equal(expectedOf(real("VAR-REP-025"), "additional_detail_registered_by"), "ACT-TECH");
    assert.equal(expectedOf(real("VAR-REP-025"), "authorization_request_resolved_by"), "ACT-RECEP");
    for (const id of ["VAR-REP-023", "VAR-REP-024", "VAR-REP-025"]) {
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-185"), `${id}: ningun Detalle se ejecuta antes de cumplir sus condiciones`);
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-140") && !traversedNodes(real(id)).has("PROC-REP-150"), `${id}: no repite 140/150`);
    }
  });

  check("[grafo] independencia operativa (BR-REP-037): el hilo tecnico nunca pasa obligatoriamente por 046/047; Recepcion resuelve por un carril propio (EVT-REP-003, 129) y vuelve al resolver", () => {
    const reach = (from: string, banned: string[]): Set<string> => {
      const seenNodes = new Set<string>([from]);
      const queue = [from];
      while (queue.length) {
        const cur = queue.shift() as string;
        for (const e of processModel.edges.filter((x) => x.from === cur)) {
          if (banned.includes(e.to) || seenNodes.has(e.to)) continue;
          seenNodes.add(e.to);
          queue.push(e.to);
        }
      }
      return seenNodes;
    };
    const lane = ["PROC-REP-046", "PROC-REP-047"];
    // ninguna salida del hilo tecnico (128 y 184) va a la consulta
    for (const n of ["PROC-REP-128", "PROC-REP-184", "PROC-REP-182", "PROC-REP-183", "PROC-REP-190"]) {
      assert.ok(!processModel.edges.some((e) => e.from === n && lane.includes(e.to)), `${n} no conduce a 046/047`);
    }
    // las unicas entradas a 046: definicion inicial (070/055/075), redefinicion posterior a una Ejecucion (127), espera (129) y el carril EVT-REP-003
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-046").map((e) => e.from).sort(), ["EVT-REP-003", "PROC-REP-070", "PROC-REP-075", "PROC-REP-127", "PROC-REP-129"]);
    assert.deepEqual(outgoing("EVT-REP-003"), ["->PROC-REP-046"]);
    assert.equal(nodeById.get("EVT-REP-003")?.type, "event");
    // desde el alta (durante la evaluacion o la ejecucion) el tecnico alcanza ejecucion sin 046/047
    const afterEval = reach("PROC-REP-184", lane);
    for (const n of ["PROC-REP-182", "PROC-REP-174", "PROC-REP-185", "PROC-REP-190"]) assert.ok(afterEval.has(n), `desde 184 se alcanza ${n} sin la consulta`);
    const afterAlta = reach("PROC-REP-128", lane);
    assert.ok(afterAlta.has("PROC-REP-190") && afterAlta.has("PROC-REP-185"), "desde 128 se continua sin la consulta");
    assert.ok(outgoing("PROC-REP-128").includes("Alta durante la ejecucion, CLIENTE_EXTERNO->PROC-REP-190"));
    // 047: la falta de respuesta no autoriza ni rechaza ni bloquea a los demas
    assert.ok(outgoing("PROC-REP-046").includes("Solicitud sin resolver, Detalles siguen pendientes de autorizacion->PROC-REP-211"), "la falta de respuesta es una solicitud sin resolver en 046, no una decision en 047");
    assert.deepEqual(reachableFrom("PROC-REP-211").includes("PROC-REP-129"), true);
    // la resolucion de Recepcion vuelve al resolver y a la ejecucion vigente (carril -> 211 -> 190)
    assert.ok(reachableFrom("EVT-REP-003").includes("PROC-REP-190"));
    // control final solo desde el resolver con todos los Detalles terminales
    assert.deepEqual(processModel.edges.filter((e) => e.to === "PROC-REP-220").map((e) => `${e.from}:${e.condition}`), ["PROC-REP-211:Todos terminales, existe completo"]);
    for (const id of ["VAR-REP-026", "VAR-REP-028", "VAR-REP-029", "VAR-REP-024", "VAR-REP-025"]) {
      const nodes = traversedNodes(real(id));
      for (const bad of ["PROC-REP-220", "PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-280"]) assert.ok(!nodes.has(bad), `${id} no adelanta ${bad}`);
    }
    // sin nodos de paralelismo
    assert.ok(!processModel.nodes.some((n) => /PARALEL|FORK|JOIN/i.test(n.id + n.name)));
  });

  check("VAR-REP-026/027/028/029 (casos F, sin respuesta, B y C): un Detalle pendiente no bloquea a otro ejecutable; la OR no llega a control final; las causas se conservan", () => {
    const o26 = orderOf(real("VAR-REP-026"));
    assert.deepEqual(o26, ["PROC-REP-190", "PROC-REP-128", "PROC-REP-190", "PROC-REP-200", "PROC-REP-210", "PROC-REP-211", "PROC-REP-129"]);
    assert.ok(!o26.includes("PROC-REP-046") && !o26.includes("PROC-REP-047") && !o26.includes("PROC-REP-220"));
    assert.equal(expectedOf(real("VAR-REP-026"), "technical_thread_waits_for_customer"), false);
    assert.equal(expectedOf(real("VAR-REP-026"), "active_execution_interrupted"), false);
    assert.equal(expectedOf(real("VAR-REP-026"), "order_situation_after_completion"), "PENDIENTE_AUTORIZACION");
    assert.equal(expectedOf(real("VAR-REP-026"), "order_goes_to_technical_control"), false);
    assert.equal(expectedOf(real("VAR-REP-026"), "collection_or_delivery_started"), false);
    assert.equal(expectedOf(real("VAR-REP-026"), "take_closed_when_no_workable_detail"), true);
    const o27 = orderOf(real("VAR-REP-027"));
    // sin respuesta: la solicitud queda sin resolver en 046 y vuelve al resolver; NO se registra una decision ficticia en 047
    assert.deepEqual(o27, ["PROC-REP-211", "PROC-REP-129", "PROC-REP-046", "PROC-REP-211"]);
    assert.ok(!o27.includes("PROC-REP-047"), "sin respuesta no pasa por la decision del cliente");
    assert.equal(factOf(real("VAR-REP-027"), "customer_response"), "SIN_RESPUESTA");
    assert.equal(expectedOf(real("VAR-REP-027"), "detail_authorized"), false);
    assert.equal(expectedOf(real("VAR-REP-027"), "detail_rejected"), false);
    assert.equal(expectedOf(real("VAR-REP-027"), "additional_detail_authorization_state"), "PENDIENTE_AUTORIZACION");
    assert.equal(expectedOf(real("VAR-REP-027"), "execution_started"), false);
    assert.equal(expectedOf(real("VAR-REP-027"), "consultation_can_be_retried"), true);
    for (const n of ["PROC-REP-080", "PROC-REP-300", "PROC-REP-305", "PROC-REP-185", "PROC-REP-190"]) assert.ok(!o27.includes(n), `sin respuesta no recorre ${n}`);
    assert.deepEqual(orderOf(real("VAR-REP-028")), ["PROC-REP-080", "PROC-REP-090", "PROC-REP-211", "PROC-REP-190", "PROC-REP-200", "PROC-REP-210", "PROC-REP-211", "PROC-REP-120"]);
    assert.equal(expectedOf(real("VAR-REP-028"), "executable_detail_continues"), true);
    assert.equal(expectedOf(real("VAR-REP-028"), "blocked_detail_unblocked_automatically"), false);
    assert.equal(expectedOf(real("VAR-REP-028"), "order_reenabled_or_requeued"), false);
    assert.deepEqual(orderOf(real("VAR-REP-029")), ["PROC-REP-211", "PROC-REP-190", "PROC-REP-200", "PROC-REP-210", "PROC-REP-211", "PROC-REP-125"]);
    assert.equal(expectedOf(real("VAR-REP-029"), "executable_detail_continues"), true);
    assert.equal(expectedOf(real("VAR-REP-029"), "review_detail_unblocked_automatically"), false);
    for (const id of ["VAR-REP-026", "VAR-REP-028", "VAR-REP-029"]) {
      assert.ok(!traversedNodes(real(id)).has("PROC-REP-140") && !traversedNodes(real(id)).has("PROC-REP-150") && !traversedNodes(real(id)).has("PROC-REP-170"), `${id}: no repite habilitacion ni cola`);
      assert.equal(orderOf(real(id)).filter((n) => n === "PROC-REP-190").length >= 1, true);
    }
    // VAR-REP-010 (caso E): la autorizacion durante la ejecucion no interrumpe ni inicia otra ejecucion; VAR-REP-011 (caso G)
    assert.equal(expectedOf(real("VAR-REP-010"), "second_simultaneous_execution_started"), false);
    assert.equal(expectedOf(real("VAR-REP-010"), "authorization_resolved_by"), "ACT-RECEP");
    assert.equal(expectedOf(real("VAR-REP-011"), "original_confirmation_authorization_and_history_kept"), true);
    assert.equal(expectedOf(real("VAR-REP-011"), "inventory_reserved_for_rejected_detail"), false);
  });

  check("[regla] BR-REP-037: ejecucion por Detalle, autorizacion diferida, sin espera obligatoria, toma/prioridad/ejecucion unica, control final y precedencia del resolver", () => {
    const t = rule("BR-REP-037");
    assert.match(t, /trabajabilidad y la posibilidad de ejecutar se evaluan POR DETALLE/);
    for (const n of ["\\(1\\) definicion vigente valida", "\\(2\\) autorizacion\\s+vigente del cliente", "\\(3\\) confirmacion\\s+tecnica vigente", "\\(4\\) compatibilidad con la estacion", "\\(5\\)\\s+factibilidad y posibilidad de reservar los insumos", "\\(6\\)\\s+ausencia de una restriccion operativa de la Orden"]) {
      assert.match(t, new RegExp(n), n);
    }
    assert.match(t, /El estado de los demas\s+Detalles[^]*no constituye por si mismo una restriccion/);
    assert.match(t, /conservan sus\s+bloqueos individuales y no se desbloquean automaticamente/);
    assert.match(t, /se CREA la solicitud de autorizacion/);
    assert.match(t, /su RESOLUCION efectiva/);
    assert.match(t, /sin exigir una respuesta inmediata del cliente y sin\s+detener la ejecucion de los Detalles habilitados/);
    assert.match(t, /no equivale a autorizacion ni a rechazo/);
    assert.match(t, /Una consulta\s+pendiente no bloquea el hilo operativo del tecnico/);
    assert.match(t, /no\s+exige que PROC-REP-046\/047 finalicen antes de que el tecnico retome un\s+Detalle independiente y ejecutable/);
    assert.match(t, /ninguna consulta pendiente la cierra\s+o libera/);
    assert.match(t, /sin repetir PROC-REP-140\/150/);
    assert.match(t, /no inicia una segunda ejecucion\s+simultanea/);
    assert.match(t, /no pasa al control tecnico final\s+\(PROC-REP-220\), ni al cobro o a la entrega/);
    assert.match(t, /REQUIERE_REVISION >\s+PENDIENTE_AUTORIZACION > PENDIENTE_RECURSOS/);
    assert.match(t, /La autorizacion comercial sigue siendo de Recepcion y la definicion\s+tecnica del tecnico/);
    // BR-REP-012: casos J, K y L y la distincion elegible / habilitado / terminal
    const d = rule("BR-REP-012");
    assert.match(d, /J\) Un Detalle trabajable mas\s+otros Detalles pendientes de autorizacion, de recursos y\/o de revision ->\s+ABIERTA_TRABAJABLE/);
    assert.match(d, /K\) Sin\s+ningun Detalle trabajable rige la precedencia 5 > 6 > 7 y se conservan\s+todas las causas/);
    assert.match(d, /L\) COMPLETO \+ otros Detalles pendientes/);
    assert.match(d, /Detalle elegible para ser seleccionado y evaluado, Detalle\s+autorizado y habilitado para iniciar ejecucion, y Detalle terminal/);
    // 128 / 129 / 046 / 047 / 184 citan la regla
    for (const n of ["PROC-REP-128", "PROC-REP-129", "PROC-REP-046", "PROC-REP-184"]) assert.ok(((nodeById.get(n) as unknown as { rules?: string[] }).rules ?? []).includes("BR-REP-037"), `${n} cita BR-REP-037`);
    assert.match(nodeText("PROC-REP-128"), /el hilo tecnico NO pasa por\s+PROC-REP-046\/047/);
    assert.match(nodeText("PROC-REP-129"), /Es una\s+espera de Recepcion y del cliente, no del tecnico/);
    assert.match(nodeText("PROC-REP-046"), /"Solicitud sin resolver, Detalles siguen pendientes de autorizacion" -> PROC-REP-211/);
    assert.match(nodeText("PROC-REP-047"), /Tampoco ofrece "Desiste sin\s+Detalles"[^]*ni "Sin respuesta" \(no es una decision/);
    assert.match(nodeText("PROC-REP-046"), /carril de gestion INDEPENDIENTE de Recepcion/);
    assert.match(nodeText("PROC-REP-211"), /Independencia operativa\s+\(BR-REP-037\)/);
    assert.match(nodeText("PROC-REP-211"), /la toma activa solo\s+se cierra cuando no queda ningun Detalle trabajable/);
    assert.match(rule("BR-REP-029"), /se CREA al registrar el alta o la redefinicion y se RESUELVE\s+de forma diferida e independiente por Recepcion/);
    assert.match(rule("BR-REP-032"), /se CREA al registrar\s+el alta y se RESUELVE de forma diferida por Recepcion/);
    assert.match(rule("BR-REP-034"), /no es una espera del\s+hilo tecnico \(BR-REP-037\)/);
    // trazabilidad Feature <-> regla
    const feat = (id: string) => featuresModel.features.find((x) => x.id === id);
    for (const id of ["FEAT-REP-002", "FEAT-REP-005"]) assert.ok(feat(id)?.business_rules.includes("BR-REP-037"), `${id} declara BR-REP-037`);
    assert.match(JSON.stringify(feat("FEAT-REP-004")), /No cerrar ni liberar la toma activa solo porque otro Detalle este\s+pendiente/);
    assert.match(JSON.stringify(feat("FEAT-REP-006")), /No adelantar el control tecnico, el cobro ni la entrega mientras haya\s+Detalles pendientes/);
    assert.match(JSON.stringify(feat("FEAT-REP-002")), /Gestionar de forma diferida e independiente las solicitudes de\s+autorizacion/);
    // responsabilidades tecnicas intactas
    for (const id of ["PROC-REP-075", "PROC-REP-127", "PROC-REP-128"]) assert.equal(nodeById.get(id)?.actor, "ACT-TECH", id);
    assert.equal(nodeById.get("PROC-REP-046")?.actor, "ACT-RECEP");
  });

  check("[regla] BR-REP-035/036: aplicacion inmediata del resultado principal, adicionales 0..N complementarias, trazabilidad separada e idempotencia", () => {
    const t = rule("BR-REP-035");
    assert.match(t, /origen del diagnostico RECEPCION[^]*requiere una evaluacion tecnica[^]*antes de iniciar su primera Ejecucion/);
    assert.match(t, /individual por Detalle/);
    assert.match(t, /con la Orden ya\s+tomada/);
    assert.match(t, /se registra sobre la DEFINICION VIGENTE/);
    assert.match(t, /tecnico,\s+fecha\/hora, version evaluada, resultado y observaciones/);
    assert.match(t, /REVISION_TECNICA no requieren una segunda confirmacion\s+independiente/);
    assert.match(t, /no sustituye la autorizacion, no la solicita de nuevo cuando\s+la definicion no cambio/);
    assert.match(t, /no garantiza stock/);
    assert.match(t, /No se reserva ni consume\s+ningun insumo durante la evaluacion/);
    assert.match(t, /la confirmacion anterior queda en el historial pero no\s+habilita la nueva definicion/);
    assert.match(t, /queda tecnicamente validada por ese\s+mismo acto y no exige una confirmacion redundante/);
    assert.match(t, /define los Detalles que\s+surgen de la revision tecnica inicial \(PROC-REP-075\) y los que detecta\s+durante la ejecucion o la evaluacion \(PROC-REP-128\)/);
    assert.match(t, /Recepcion\s+\(ACT-RECEP\) mantiene la definicion preliminar inicial \(PROC-REP-070\),\s+consulta al cliente y registra su autorizacion o desistimiento/);
    assert.match(t, /No se agregan estados a la Orden/);
    assert.match(t, /no se crea\s+una toma nueva para evaluar/);
    const r036 = rule("BR-REP-036");
    assert.match(r036, /registra EXACTAMENTE UN resultado principal: CONFIRMADO,\s+DESCARTADO o REQUIERE_REDEFINICION/);
    assert.match(r036, /se APLICA DE INMEDIATO sobre el\s+Detalle original, en el momento en que se registra/);
    assert.match(r036, /el efecto no\s+se difiere detras de la consulta al cliente de los Detalles nuevos/);
    assert.match(r036, /cero, una o varias reparaciones adicionales/);
    assert.match(r036, /no un cuarto resultado ni una alternativa/);
    assert.match(r036, /no modifica\s+automaticamente el Detalle original/);
    assert.match(r036, /DESCARTADO \+\s+adicional y REQUIERE_REDEFINICION \+ otro trabajo independiente son\s+combinaciones validas/);
    assert.match(r036, /El orden es: primero el resultado principal y su\s+efecto sobre el Detalle original, luego las altas \(0\.\.N\), que solo CREAN las\s+solicitudes de autorizacion de los Detalles nuevos, y despues el hilo\s+tecnico continua sin esperar su resolucion/);
    assert.match(r036, /la existencia de Detalles adicionales\s+pendientes no lo bloquea ni invalida su confirmacion/);
    assert.match(r036, /desde el\s+registro el Detalle no puede seleccionarse, ejecutarse ni reservar\s+insumos/);
    assert.match(r036, /No se invoca el\s+resolver hasta registrar las altas pendientes \(PROC-REP-300 -> PROC-REP-184\)/);
    assert.match(r036, /la\s+Orden no finaliza ni pasa a TODO_CANCELADO antes de registrar y encaminar\s+el Detalle nuevo/);
    assert.match(r036, /desde el registro la\s+definicion anterior queda invalidada y no puede ejecutarse/);
    assert.match(r036, /el TECNICO registra de inmediato una nueva definicion vigente/);
    assert.match(r036, /no se reservan insumos ni se inicia ejecucion sobre\s+una definicion invalidada/);
    assert.match(r036, /Se reutiliza PROC-REP-127 pero no el circuito de\s+espera PROC-REP-125\/126/);
    assert.match(r036, /efecto aplicado\)/);
    assert.match(r036, /su historial es independiente del de\s+la evaluacion del Detalle original/);
    assert.match(r036, /sin invalidar la autorizacion del Detalle original/);
    assert.match(r036, /Idempotencia: el efecto\s+\(cancelacion, redefinicion, alta\) se aplica una sola vez/);
    assert.match(r036, /no se repiten PROC-REP-140\/150 en una Orden ya\s+habilitada/);
    assert.match(rule("BR-REP-032"), /El tecnico es el\s+responsable de definir y registrar el Detalle nuevo \(no Recepcion\)/);
    assert.match(rule("BR-REP-029"), /Recepcion\s+consulta al cliente y registra autorizacion o desistimiento/);
    assert.match(rule("BR-REP-029"), /PROC-REP-127, registrada por el tecnico/);
    assert.match(nodeText("PROC-REP-127"), /sin pasar por la espera de PROC-REP-125\/126/);
    assert.match(nodeText("PROC-REP-128"), /cero, una o varias altas, que\s+vuelven a PROC-REP-184/);
  });

  check("[regla] resolver: un Detalle descartado o con definicion invalidada no es trabajable para ejecutar, sin nuevos estados ni cambio de precedencia", () => {
    const d = rule("BR-REP-012");
    assert.match(d, /Refinamiento de la\s+regla derivada es_trabajable \(sin nuevos estados\)/);
    assert.match(d, /un Detalle tampoco es\s+trabajable para ejecutar desde que se registra un resultado tecnico que\s+lo impide/);
    assert.match(d, /nunca hay una ventana en la que el resolver trate\s+como trabajable un Detalle que el resultado tecnico ya impide/);
    assert.match(d, /Mientras\s+se registran las reparaciones adicionales \(PROC-REP-184 \/ PROC-REP-128\) la\s+Orden no se evalua con el resolver, por lo que no se cancela\s+prematuramente/);
    assert.match(d, /5\s+REQUIERE_REVISION; 6 PENDIENTE_AUTORIZACION/);
    assert.match(d, /7 PENDIENTE_RECURSOS \(antes prioridad\s+6\)/);
    assert.match(d, /trabajable" significa ELEGIBLE para ser seleccionado y\s+evaluado/);
    assert.match(d, /no implica estar habilitado para iniciar la Ejecucion/);
    // no se agregaron estados ni situaciones agregadas nuevas
    assert.ok(!/DESCARTADO|PENDIENTE_EVALUACION/.test(JSON.stringify(nodeById.get("PROC-REP-211") ?? {}).replace(/DIAGNOSTICO_DESCARTADO/g, "")));
    // 211 conserva sus salidas V1.4 de la iteracion anterior
    assert.ok(outgoing("PROC-REP-211").includes("PENDIENTE_AUTORIZACION->PROC-REP-129"));
    assert.ok(outgoing("PROC-REP-211").includes("REQUIERE_REVISION->PROC-REP-125"));
    assert.ok(outgoing("PROC-REP-211").includes("PENDIENTE_RECURSOS->PROC-REP-120"));
  });

  check("[regla] se puede tomar una OR con Detalles sin confirmar: la toma y la estacion agregada no exigen confirmacion; el resolver conserva su politica", () => {
    assert.match(nodeText("PROC-REP-172"), /NO exige\s+que sus Detalles ya esten confirmados tecnicamente/);
    assert.match(nodeText("PROC-REP-181"), /pendiente de confirmacion tecnica SI es\s+seleccionable/);
    assert.ok(!processModel.edges.some((e) => (e.from === "PROC-REP-172" || e.from === "PROC-REP-180" || e.from === "PROC-REP-170") && /182|183/.test(e.to)), "ni la cola ni la toma pasan por la evaluacion");
    const d = rule("BR-REP-012");
    assert.match(d, /"trabajable" significa ELEGIBLE para ser seleccionado y\s+evaluado/);
    assert.match(d, /no implica estar habilitado para iniciar la Ejecucion/);
    assert.match(d, /no genera REQUIERE_REVISION ni bloquea la toma/);
    assert.match(d, /5\s+REQUIERE_REVISION; 6 PENDIENTE_AUTORIZACION/);
    assert.match(d, /7 PENDIENTE_RECURSOS \(antes prioridad\s+6\)/);
    const f4 = featuresModel.features.find((x) => x.id === "FEAT-REP-004");
    assert.ok(!f4?.process_nodes.some((n) => n === "PROC-REP-182" || n === "PROC-REP-183"));
    assert.ok(!f4?.business_rules.some((b) => b === "BR-REP-035" || b === "BR-REP-036"));
  });

  check("[trazabilidad] FEAT-REP-005 es propietaria de 182/183 y BR-REP-035/036; FEAT-REP-009 declara BR-REP-036; FEAT-REP-001/002 no cambian de responsabilidad", () => {
    const feat = (id: string) => featuresModel.features.find((x) => x.id === id);
    for (const n of ["PROC-REP-182", "PROC-REP-183", "PROC-REP-184"]) assert.ok(feat("FEAT-REP-005")?.process_nodes.includes(n), n);
    for (const b of ["BR-REP-035", "BR-REP-036"]) assert.ok(feat("FEAT-REP-005")?.business_rules.includes(b), b);
    assert.ok(feat("FEAT-REP-009")?.business_rules.includes("BR-REP-036"));
    for (const id of ["FEAT-REP-001", "FEAT-REP-002"]) {
      assert.ok(!feat(id)?.process_nodes.some((n) => n === "PROC-REP-182" || n === "PROC-REP-183"), id);
      assert.ok(!feat(id)?.business_rules.some((b) => b === "BR-REP-035"), id);
    }
    assert.match(nodeText("PROC-REP-185"), /ademas exige\s+que el Detalle haya pasado por PROC-REP-182/);
    // el descarte reutiliza la cancelacion individual (300) y los demas origenes conservan su recorrido de definicion
    for (const n of ["PROC-REP-127", "PROC-REP-128"]) assert.ok(outgoing(n).some((e) => e.endsWith("->PROC-REP-080")), `${n} -> 080 para los otros origenes`);
  });

  check("la seleccion de reparaciones diagnosticadas no crea Detalles ni estados en FEAT-REP-001", () => {
    const text = rule("BR-REP-026");
    assert.match(text, /NO crea Detalles en FEAT-REP-001/);
    assert.match(text, /no define estados\s+PENDIENTE, CONFIRMADA ni DESCARTADA en el Detalle/);
    assert.match(text, /RECEPCION/);
    assert.match(text, /REVISION_TECNICA/);
  });
}

console.log("");
if (failures > 0) {
  console.error(`FAILED: ${failures} test(s) failed.`);
  process.exit(1);
}
console.log("OK: all scenario tests passed.");
