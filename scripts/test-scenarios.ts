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
import { loadYaml, type ProcessModel } from "./lib/process-model";
import type { FeatureModel } from "./lib/feature-model";
import { deriveScenarioFeatures } from "./lib/feature-scenario-mapping";
import { isProcessEdgeStep, type Scenario, type ScenarioModel } from "./lib/scenario-model";
import { findDuplicateIds, validateScenario } from "./validate-scenarios";

const PROCESS_FILE = "business/processes/repair-management-v1.3.yaml";
const FEATURES_FILE = "business/features/repair-management-features-v1.3.yaml";
const SCENARIOS_FILE = "business/scenarios/repair-management-scenarios-v1.3.yaml";
const SCHEMA_FILE = "business/schemas/scenario.schema.json";

const processModel = loadYaml<ProcessModel>(PROCESS_FILE);
const featuresModel = loadYaml<FeatureModel>(FEATURES_FILE);
const scenariosModel = loadYaml<ScenarioModel>(SCENARIOS_FILE);
const featureIds = new Set(featuresModel.features.map((feature) => feature.id));
const rulesModel = loadYaml<{ rules: { id: string; name: string; description?: string }[] }>(
  "business/rules/business-rules-v1.3.yaml"
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

check("orden: REPARACION_LISTA(240) -> 250 -> 290 (informar) -> 270 (entrega/devolucion) -> cierre -> FIN", () => {
  const order = orderOf(real("HP-REP-002"));
  const at = (id: string): number => order.indexOf(id);
  assert.ok(at("PROC-REP-240") < at("PROC-REP-250"));
  assert.ok(at("PROC-REP-250") < at("PROC-REP-290"));
  assert.ok(at("PROC-REP-290") < at("PROC-REP-270"), "el resultado se informa ANTES de registrar la devolucion");
  assert.ok(at("PROC-REP-270") < at("EVT-REP-999"), "la entrega/devolucion ocurre antes del cierre/fin");
  assert.deepEqual(order.slice(-5), ["PROC-REP-240", "PROC-REP-250", "PROC-REP-290", "PROC-REP-270", "EVT-REP-999"]);
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
  assert.match(desc("EVT-REP-002"), /Generar garantia/);
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

check("4) se identifica/referencia el Detalle origen (035 output, 070 + BR-REP-019)", () => {
  const node = nodeById.get("PROC-REP-035");
  assert.ok((node?.outputs ?? []).some((output) => /Detalle\(s\) origen/.test(output)));
  assert.ok((nodeById.get("PROC-REP-070")?.rules ?? []).includes("BR-REP-019"));
  assert.match(desc("PROC-REP-070"), /Detalle origen/);
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

check("12) mantiene price snapshot (070) sin que implique pago", () => {
  assert.ok(traversedNodes(real("HP-REP-003")).has("PROC-REP-070"));
  assert.equal(factOf(real("HP-REP-003"), "price_snapshot_registered"), true);
  assert.equal(factOf(real("HP-REP-003"), "payment_required"), false);
  assert.match(desc("PROC-REP-070"), /precio registrado no implica/i);
});

check("13) recorre notificacion al cliente (260)", () => {
  assert.ok(traversedNodes(real("HP-REP-003")).has("PROC-REP-260"));
  assert.equal(expectedOf(real("HP-REP-003"), "client_notified"), true);
});

check("14) recorre documentacion final y entrega al cliente: 260 -> 265 -> 280 -> 270", () => {
  const order = orderOf(real("HP-REP-003"));
  assert.deepEqual(order.slice(-6), ["PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-280", "PROC-REP-270", "EVT-REP-999"]);
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

check("20) HP-REP-002 sigue pasando (290 -> 270 -> fin, sin cobro)", () => {
  assert.deepEqual(errorsOf(real("HP-REP-002")), []);
  assert.deepEqual(orderOf(real("HP-REP-002")).slice(-4), ["PROC-REP-250", "PROC-REP-290", "PROC-REP-270", "EVT-REP-999"]);
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
  // FEAT-REP-007: own node 265 (delivery-condition gate) plus shared ALWAYS nodes (070, 280); never its own 266
  const r7 = activationReasons["FEAT-REP-007"];
  assert.ok(r7.some((r) => r.includes("nodo propio PROC-REP-265")));
  assert.ok(r7.some((r) => r.includes("PROC-REP-070") && r.includes("(ALWAYS)")));
  assert.ok(r7.some((r) => r.includes("PROC-REP-280") && r.includes("(ALWAYS)")));
  assert.ok(!r7.some((r) => r.includes("PROC-REP-266")));
});

check("HP-REP-003 converge con HP-REP-001 desde PROC-REP-040 (mismo circuito tecnico)", () => {
  const a = orderOf(real("HP-REP-001"));
  const b = orderOf(real("HP-REP-003"));
  const tail = (o: string[], from: string, to: string): string[] => o.slice(o.indexOf(from), o.indexOf(to) + 1);
  assert.deepEqual(tail(b, "PROC-REP-040", "PROC-REP-260"), tail(a, "PROC-REP-040", "PROC-REP-260"));
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

const MVP_V2_VARIANT_IDS = ["VAR-REP-001", "VAR-REP-002", "VAR-REP-003"];
const MVP_V2_EXCEPTION_IDS = [
  "EXC-REP-001",
  "EXC-REP-002",
  "EXC-REP-003",
  "EXC-REP-004",
  "EXC-REP-005",
];
const MVP_V2_HAPPY_PATH_IDS = ["HP-REP-001", "HP-REP-002", "HP-REP-003"];

check("el scope de MVP v2 es exactamente 3 HAPPY_PATH + 3 VARIANT + 5 EXCEPTION, sin EDGE_CASE", () => {
  const byType = (type: Scenario["type"]): string[] =>
    scenariosModel.scenarios.filter((s) => s.type === type).map((s) => s.id).sort();
  assert.deepEqual(byType("HAPPY_PATH"), [...MVP_V2_HAPPY_PATH_IDS].sort());
  assert.deepEqual(byType("VARIANT"), [...MVP_V2_VARIANT_IDS].sort());
  assert.deepEqual(byType("EXCEPTION"), [...MVP_V2_EXCEPTION_IDS].sort());
  assert.deepEqual(byType("EDGE_CASE"), []);
  assert.equal(scenariosModel.scenarios.length, 11);
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
  assert.deepEqual(real("VAR-REP-001").applies_to, ["HP-REP-001", "HP-REP-003"]);
  assert.deepEqual(real("VAR-REP-002").applies_to, ["HP-REP-002"]);
});

check("SIN_REPARACION tras EN_REVISION (CAND-REP-010/017) NO esta en el scope de MVP v2", () => {
  for (const id of [...MVP_V2_VARIANT_IDS, ...MVP_V2_EXCEPTION_IDS]) {
    assert.ok(!traversedNodes(real(id)).has("PROC-REP-069"), `${id} no deberia llegar a PROC-REP-069 (SIN_REPARACION)`);
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
  // PROC-REP-212 ("¿Iniciar un Detalle de reparacion?") paso a ser parte
  // del recorrido base de todo Happy Path -se alcanza siempre desde
  // PROC-REP-180, no solo en una continuacion multi-Detalle-, asi que
  // 212::Si::181 ya no es un mecanismo exclusivo de Multi-Detalle: es la
  // rama que cualquier Happy Path toma para seguir adelante. Lo que sigue
  // siendo exclusivamente mecanico (nunca declarado como steps[] de un
  // Scenario real) es: llegar a 212 DESDE 211 (continuar tras completar
  // un Detalle con otro pendiente) y decidir liberar (212::No::213) en
  // vez de seguir.
  const mechanismEdges = new Set([
    "PROC-REP-211::Existe Detalle trabajable, sin toma activa::PROC-REP-170",
    "PROC-REP-211::Existe Detalle trabajable, toma activa::PROC-REP-212",
    "PROC-REP-212::No::PROC-REP-213",
  ]);
  for (const scenario of scenariosModel.scenarios) {
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

console.log("");
if (failures > 0) {
  console.error(`FAILED: ${failures} test(s) failed.`);
  process.exit(1);
}
console.log("OK: all scenario tests passed.");
