/**
 * Dependency-free tests for the V1.4 iteration "simplificacion de PROC-REP-045 y PROC-REP-047":
 *
 *  - an Order WITHOUT Details never asks the customer to authorize Details (no 046/047) and never reaches the
 *    resolver (211) with cantidad_detalles = 0 (fixes the AUD-V14-002 route 055 -> 046 -> 047 -> 211);
 *  - PROC-REP-047 has exactly three business decisions and none of the internal conditions;
 *  - "sin respuesta" is an unresolved request (046 -> 211), never a fake decision in 047;
 *  - receipt, historic enabling and pending feasibility are resolved by the system (211), and a partial
 *    authorization in an already enabled Order no longer skips feasibility (AUD-V14-003);
 *  - cancellation keeps custody and the refund of money (BR-REP-033, BR-REP-038).
 *
 * Run: npm run test:customer-decision:v1.4
 * It works over the parsed models only (never over YAML text) and over the real Scenarios.
 */
import assert from "node:assert/strict";
import { edgeKey, loadYaml, type BusinessRule, type ProcessModel } from "./lib/process-model";
import { isProcessEdgeStep, type Scenario, type ScenarioModel } from "./lib/scenario-model";

const model = loadYaml<ProcessModel>("business/processes/repair-management-v1.4.yaml");
const rules = loadYaml<{ rules: BusinessRule[] }>("business/rules/business-rules-v1.4.yaml").rules;
const scenarios = loadYaml<ScenarioModel>("business/scenarios/repair-management-scenarios-v1.4.yaml").scenarios;

let failures = 0;
function check(name: string, fn: () => void): void {
  try {
    fn();
    console.log(`  OK   ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`  FAIL ${name}`);
    console.log(`       ${(error as Error).message.split("\n").slice(0, 8).join("\n       ")}`);
  }
}

const node = (id: string) => model.nodes.find((n) => n.id === id);
const text = (id: string): string => (node(id)?.description ?? "").replace(/\s+/g, " ");
const rule = (id: string): string => (rules.find((r) => r.id === id)?.description ?? "").replace(/\s+/g, " ");
const out = (from: string): string[] => model.edges.filter((e) => e.from === from).map((e) => `${e.condition ?? ""}->${e.to}`).sort();
const into = (to: string): string[] => model.edges.filter((e) => e.to === to).map((e) => e.from).sort();
const scenario = (id: string): Scenario => {
  const s = scenarios.find((x) => x.id === id);
  assert.ok(s, `existe ${id}`);
  return s;
};
const order = (s: Scenario): string[] => {
  const steps = s.steps.filter(isProcessEdgeStep);
  return [steps[0].from, ...steps.map((st) => st.to)];
};

/** Nodes reachable from `start` without traversing `banned` nodes nor edges whose condition requires existing Details. */
function reachableWithoutDetails(start: string, banned: string[]): Set<string> {
  const requiresDetails = (c: string | undefined): boolean => /Detalles definidos/.test(c ?? "");
  const seen = new Set<string>([start]);
  const queue = [start];
  while (queue.length > 0) {
    const cur = queue.shift() as string;
    for (const e of model.edges.filter((x) => x.from === cur)) {
      if (banned.includes(e.to) || seen.has(e.to) || requiresDetails(e.condition)) continue;
      seen.add(e.to);
      queue.push(e.to);
    }
  }
  return seen;
}

console.log("\nIteracion 10 - simplificacion de PROC-REP-045 y PROC-REP-047\n");

console.log("A) Orden sin Detalles conocidos\n");

check("1-2) 045 [No] -> 055 -> 056 (CLIENTE_EXTERNO): la OR queda EN_REVISION y espera el diagnostico sin consultar por Detalle", () => {
  assert.ok(out("PROC-REP-045").includes("No->PROC-REP-055"));
  assert.ok(out("PROC-REP-055").includes("CLIENTE_EXTERNO->PROC-REP-056"));
  assert.ok(!out("PROC-REP-055").some((o) => o.endsWith("->PROC-REP-046")), "055 ya no llama a 046");
  assert.deepEqual(out("PROC-REP-056"), ["Acepta la revision tecnica->PROC-REP-050", "Desiste sin Detalles->PROC-REP-306"].sort());
  assert.equal(node("PROC-REP-056")?.actor, "ACT-RECEP");
  assert.match(text("PROC-REP-055"), /La Orden pasa a EN_REVISION/);
  // se conserva el circuito inicial: comprobante (050/060), revision (065/068) y definicion por el tecnico (075)
  assert.ok(out("PROC-REP-050").includes("Si->PROC-REP-060"));
  assert.ok(out("PROC-REP-060").includes("Aun en revision->PROC-REP-065"));
  assert.deepEqual(out("PROC-REP-065"), ["->PROC-REP-068"]);
  assert.ok(out("PROC-REP-068").includes("Si->PROC-REP-075"));
  assert.equal(node("PROC-REP-075")?.actor, "ACT-TECH");
});

check("9) una OR sin Detalles no llega a 046/047/129/090/211 ni a factibilidad antes de que el tecnico defina los Detalles (075)", () => {
  const reach = reachableWithoutDetails("PROC-REP-056", ["PROC-REP-075"]);
  for (const forbidden of ["PROC-REP-046", "PROC-REP-047", "PROC-REP-129", "PROC-REP-080", "PROC-REP-090", "PROC-REP-211", "PROC-REP-140", "PROC-REP-300", "PROC-REP-305"]) {
    assert.ok(!reach.has(forbidden), `sin Detalles no se alcanza ${forbidden}`);
  }
  // si, en cambio, el desistimiento y el cierre SIN_REPARACION
  for (const expected of ["PROC-REP-050", "PROC-REP-060", "PROC-REP-065", "PROC-REP-068", "PROC-REP-069", "PROC-REP-306", "PROC-REP-250"]) assert.ok(reach.has(expected), `se alcanza ${expected}`);
  // AUD-V14-002: el recorrido 055 -> 046 -> 047 -> 211 [Sin respuesta] ya no existe
  assert.ok(!model.edges.some((e) => e.from === "PROC-REP-055" && e.to === "PROC-REP-046"));
  assert.ok(!model.edges.some((e) => e.from === "PROC-REP-047" && /Sin respuesta/.test(e.condition ?? "")));
  assert.deepEqual(into("PROC-REP-046"), ["EVT-REP-003", "PROC-REP-070", "PROC-REP-075", "PROC-REP-127", "PROC-REP-129"], "046 solo se invoca desde puntos donde ya existen Detalles");
  assert.match(text("PROC-REP-070"), /cantidad_detalles pasa de 0 a >=1/);
  assert.match(text("PROC-REP-056"), /NO se consulta al cliente por\s+Detalle|NO se consulta al cliente por Detalle/);
  assert.match(text("PROC-REP-046"), /NO se invoca mientras no exista ningun\s+Detalle|NO se invoca mientras no exista ningun Detalle/);
});

check("3-5) VAR-REP-001: la OR espera la revision, el tecnico define los Detalles y recien entonces Recepcion consulta al cliente, que acepta los trabajos", () => {
  const o = order(scenario("VAR-REP-001"));
  assert.deepEqual(o, ["PROC-REP-045", "PROC-REP-055", "PROC-REP-056", "PROC-REP-050", "PROC-REP-060", "PROC-REP-065", "PROC-REP-068", "PROC-REP-075", "PROC-REP-046", "PROC-REP-047", "PROC-REP-211", "PROC-REP-080"]);
  assert.ok(o.indexOf("PROC-REP-075") < o.indexOf("PROC-REP-046"));
});

check("la revision sin reparacion conserva el circuito SIN_REPARACION existente, con custodia y control comercial, sin Detalle ficticio", () => {
  assert.ok(out("PROC-REP-068").includes("No->PROC-REP-069"));
  assert.deepEqual(out("PROC-REP-069"), ["->PROC-REP-250"]);
  assert.match(text("PROC-REP-056"), /sin crear un Detalle ficticio/);
  const o = order(scenario("VAR-REP-030"));
  assert.ok(o.includes("PROC-REP-069") && o.includes("PROC-REP-267") && o.includes("PROC-REP-268"));
  assert.ok(!o.includes("PROC-REP-046") && !o.includes("PROC-REP-047"));
});

check("desistimiento sin Detalles: via propia de la etapa (056 -> 306), con custodia y saldo, separada de la autorizacion por Detalle", () => {
  assert.deepEqual(out("PROC-REP-306"), ["Custodia sin confirmar->PROC-REP-271", "Equipo bajo custodia->PROC-REP-270", "Sin equipo bajo custodia->PROC-REP-268"].sort());
  assert.deepEqual(into("PROC-REP-306"), ["PROC-REP-056"]);
  const o = order(scenario("VAR-REP-004"));
  assert.deepEqual(o.slice(-5), ["PROC-REP-055", "PROC-REP-056", "PROC-REP-306", "PROC-REP-268", "EVT-REP-999"]);
  assert.match(rule("BR-REP-027"), /PROC-REP-056, "Desiste sin Detalles"/);
});

console.log("\nB) Las tres decisiones de PROC-REP-047\n");

check("5-7) 047 ofrece exactamente tres decisiones: acepta trabajos, rechaza algunos Detalles, rechaza todos los trabajos", () => {
  assert.equal(node("PROC-REP-047")?.type, "decision");
  assert.deepEqual(out("PROC-REP-047"), ["Acepta trabajos->PROC-REP-211", "Rechaza algunos Detalles->PROC-REP-300", "Rechaza todos los trabajos->PROC-REP-305"].sort());
  for (const code of ["ACEPTA_TRABAJOS", "RECHAZA_ALGUNOS_DETALLES", "RECHAZA_TODOS_LOS_TRABAJOS"]) assert.ok(text("PROC-REP-047").includes(code), code);
  // nada que el cliente no decida: ni comprobante, ni habilitacion, ni factibilidad, ni estado, ni desistimiento sin Detalles, ni "sin respuesta"
  assert.ok(!out("PROC-REP-047").some((o) => /comprobante|factibilidad|habilitad|Desiste|Sin respuesta|trabajable|cola/i.test(o)));
  for (const internal of ["PROC-REP-050", "PROC-REP-060", "PROC-REP-080", "PROC-REP-090", "PROC-REP-306"]) {
    assert.ok(!model.edges.some((e) => e.from === "PROC-REP-047" && e.to === internal), `047 no enruta directamente a ${internal}`);
  }
  assert.match(text("PROC-REP-047"), /sin\s+generar una nueva definicion y sin ejecutar ninguna reparacion todavia/);
  assert.match(rule("BR-REP-028"), /PROC-REP-047 ofrece exactamente tres decisiones del cliente/);
});

check("las tres decisiones vuelven al resolver (211), que enruta el comprobante y la factibilidad por hitos; nada lo decide el cliente", () => {
  assert.deepEqual(out("PROC-REP-300").filter((o) => o.endsWith("->PROC-REP-211")), ["Cancelacion fuera de la evaluacion tecnica->PROC-REP-211"]);
  assert.deepEqual(out("PROC-REP-305"), ["->PROC-REP-211"]);
  assert.ok(out("PROC-REP-211").includes("Antes del comprobante de recepcion->PROC-REP-050"));
  assert.ok(out("PROC-REP-211").includes("Comprobante emitido, factibilidad pendiente->PROC-REP-080"));
  assert.ok(out("PROC-REP-080").length === 1 && out("PROC-REP-080")[0] === "->PROC-REP-090");
  assert.ok(out("PROC-REP-090").includes("Orden ya habilitada->PROC-REP-211"), "tras evaluar la factibilidad el hito historico devuelve al resolver");
  assert.equal(node("PROC-REP-080")?.actor, "ACT-SYSTEM", "la factibilidad es del sistema, no de Recepcion ni una decision comercial");
  for (const from of ["PROC-REP-046", "PROC-REP-047", "PROC-REP-056"]) assert.ok(!model.edges.some((e) => e.from === from && e.to === "PROC-REP-080"), `${from} no traslada la factibilidad a Recepcion`);
  assert.match(text("PROC-REP-211"), /Con cantidad_detalles = 0 este nodo no se invoca/);
  assert.match(rule("BR-REP-034"), /La factibilidad sigue siendo del sistema por Detalle: no la decide ni la evalua Recepcion/);
});

check("11) la factibilidad se evalua despues de la autorizacion: HP-REP-001, VAR-REP-001/008/010/012 recorren 047 -> 211 -> (050 | 080)", () => {
  const hp = order(scenario("HP-REP-001"));
  assert.deepEqual(hp.slice(hp.indexOf("PROC-REP-047"), hp.indexOf("PROC-REP-047") + 4), ["PROC-REP-047", "PROC-REP-211", "PROC-REP-050", "PROC-REP-060"]);
  assert.ok(hp.indexOf("PROC-REP-060") < hp.indexOf("PROC-REP-080"), "el comprobante precede a la factibilidad");
  for (const id of ["VAR-REP-001", "VAR-REP-008", "VAR-REP-010", "VAR-REP-012"]) {
    const o = order(scenario(id));
    const i = o.lastIndexOf("PROC-REP-047");
    assert.deepEqual(o.slice(i, i + 3), ["PROC-REP-047", "PROC-REP-211", "PROC-REP-080"], id);
  }
});

check("10) una autorizacion posterior no regenera el comprobante: el sistema ya lo emitio y ruta a factibilidad, nunca a 050/060", () => {
  for (const id of ["VAR-REP-001", "VAR-REP-008", "VAR-REP-010", "VAR-REP-012", "VAR-REP-036"]) {
    const o = order(scenario(id));
    const i = o.lastIndexOf("PROC-REP-047");
    assert.ok(!o.slice(i).includes("PROC-REP-050") && !o.slice(i).includes("PROC-REP-060"), `${id}: no se regenera el comprobante`);
    assert.ok(o.filter((n) => n === "PROC-REP-060").length <= 1, `${id}: un solo comprobante`);
  }
  assert.match(rule("BR-REP-031"), /No se genera un comprobante nuevo\s+automaticamente por cada cambio posterior/);
});

console.log("\nC) Sin respuesta, parcial en una OR habilitada y otros Detalles\n");

check("8) el cliente no responde: la solicitud queda sin resolver en 046 (-> 211), sin pasar por una falsa decision en 047; EVT-REP-003 y 129 se conservan", () => {
  assert.ok(out("PROC-REP-046").includes("Solicitud sin resolver, Detalles siguen pendientes de autorizacion->PROC-REP-211"));
  assert.ok(out("PROC-REP-046").includes("Decision del cliente registrada->PROC-REP-047"));
  assert.deepEqual(out("EVT-REP-003"), ["->PROC-REP-046"]);
  assert.deepEqual(out("PROC-REP-129"), ["->PROC-REP-046"]);
  assert.ok(out("PROC-REP-211").includes("PENDIENTE_AUTORIZACION->PROC-REP-129"));
  const o = order(scenario("VAR-REP-027"));
  assert.deepEqual(o, ["PROC-REP-211", "PROC-REP-129", "PROC-REP-046", "PROC-REP-211"]);
  assert.ok(!o.includes("PROC-REP-047"), "sin decision ficticia");
  assert.ok(!o.some((n) => ["PROC-REP-300", "PROC-REP-305", "PROC-REP-080", "PROC-REP-190"].includes(n)), "no autoriza, no rechaza y no inicia ejecucion");
  assert.match(rule("BR-REP-037"), /PROC-REP-046, "Solicitud sin\s*resolver": no se registra ninguna decision ni se pasa por PROC-REP-047/);
});

check("12) la autorizacion parcial en una OR ya habilitada no omite la factibilidad (AUD-V14-003): 047 [Rechaza algunos] -> 300 -> 211 -> 080 -> 090 -> 211 -> 190", () => {
  const o = order(scenario("VAR-REP-036"));
  assert.deepEqual(o, ["EVT-REP-003", "PROC-REP-046", "PROC-REP-047", "PROC-REP-300", "PROC-REP-211", "PROC-REP-080", "PROC-REP-090", "PROC-REP-211", "PROC-REP-190"]);
  assert.ok(!o.some((n) => ["PROC-REP-140", "PROC-REP-150", "PROC-REP-170", "PROC-REP-050", "PROC-REP-060"].includes(n)), "no se re-habilita, no se encola y no hay comprobante nuevo");
  // la salida 211 -> 080 ya no esta limitada a Ordenes sin habilitar
  assert.match(text("PROC-REP-211"), /con la Orden sin habilitar\s+o ya habilitada\) -> PROC-REP-080/);
  assert.match(rule("BR-REP-034"), /con la\s+Orden sin habilitar O ya habilitada/);
  const s = scenario("VAR-REP-036");
  assert.equal(s.expected.find((e) => e.key === "authorized_detail_skips_feasibility")?.value, false);
  assert.equal(s.expected.find((e) => e.key === "feasibility_decided_by_customer")?.value, false);
});

check("13) las demas reparaciones ejecutables no se bloquean: 211 devuelve la Ejecucion vigente tras la factibilidad y no se interrumpe nada", () => {
  for (const id of ["VAR-REP-010", "VAR-REP-011", "VAR-REP-036"]) {
    const o = order(scenario(id));
    assert.equal(o[o.length - 1], "PROC-REP-190", `${id} continua la Ejecucion vigente`);
    assert.ok(!o.includes("PROC-REP-200") && !o.includes("PROC-REP-185"), `${id} no interrumpe ni inicia otra ejecucion`);
  }
  assert.equal(scenario("VAR-REP-036").expected.find((e) => e.key === "executable_detail_blocked")?.value, false);
  assert.match(text("PROC-REP-211"), /no\s+interrumpe la Ejecucion vigente ni libera la toma|no interrumpe la Ejecucion vigente ni\s+libera la toma/);
});

check("6) rechaza algunos Detalles: se cancelan solo los rechazados (300) y los aceptados continuan; VAR-REP-005/013 siguen a 050 u 080 segun el comprobante", () => {
  assert.deepEqual(order(scenario("VAR-REP-005")), ["PROC-REP-070", "PROC-REP-046", "PROC-REP-047", "PROC-REP-300", "PROC-REP-211", "PROC-REP-050"]);
  assert.deepEqual(order(scenario("VAR-REP-013")).slice(-3), ["PROC-REP-300", "PROC-REP-211", "PROC-REP-080"]);
  assert.match(text("PROC-REP-047"), /PROC-REP-300 cancela unicamente los rechazados/);
  assert.match(rule("BR-REP-028"), /se cancelan unicamente los\s+rechazados/);
});

console.log("\nD) Cierre, custodia, devolucion y otros origenes\n");

check("14) rechaza todos los trabajos: 305 -> 211 -> custodia/fin pasando siempre por la verificacion de saldo (268) y la devolucion de dinero", () => {
  const v6 = order(scenario("VAR-REP-006"));
  assert.deepEqual(v6.slice(-4), ["PROC-REP-305", "PROC-REP-211", "PROC-REP-268", "EVT-REP-999"]);
  const v7 = order(scenario("VAR-REP-007"));
  assert.deepEqual(v7.slice(-5), ["PROC-REP-305", "PROC-REP-211", "PROC-REP-270", "PROC-REP-268", "EVT-REP-999"]);
  const v32 = order(scenario("VAR-REP-032"));
  assert.deepEqual(v32.slice(-5), ["PROC-REP-270", "PROC-REP-268", "PROC-REP-267", "PROC-REP-268", "EVT-REP-999"]);
  const v33 = order(scenario("VAR-REP-033"));
  assert.ok(v33.includes("PROC-REP-267") && v33[v33.length - 1] === "EVT-REP-999");
  // los exits de cancelacion total de 211 conservan custodia y todos terminan en 268
  for (const c of ["Todos cancelados, equipo bajo custodia->PROC-REP-270", "Todos cancelados, sin equipo bajo custodia->PROC-REP-268", "Todos cancelados, custodia sin confirmar->PROC-REP-271"]) assert.ok(out("PROC-REP-211").includes(c), c);
  assert.deepEqual(into("EVT-REP-999"), ["PROC-REP-268"], "todo fin pasa por la verificacion de saldo");
  assert.match(text("PROC-REP-047"), /custodia fisica del equipo\s+\(BR-REP-033\) y el saldo, los anticipos y su\s+devolucion \(BR-REP-038\)/);
});

check("15) los demas origenes no sufren regresiones: 055 y 070 conservan su salida hacia 050 y ninguno pasa por 056/046/047", () => {
  assert.ok(out("PROC-REP-055").includes("Origen distinto de CLIENTE_EXTERNO->PROC-REP-050"));
  assert.ok(out("PROC-REP-070").includes("Origen distinto de CLIENTE_EXTERNO->PROC-REP-050"));
  assert.ok(out("PROC-REP-075").includes("Origen distinto de CLIENTE_EXTERNO->PROC-REP-080"));
  for (const id of ["HP-REP-002", "HP-REP-003", "VAR-REP-002", "EXC-REP-004"]) {
    const o = order(scenario(id));
    for (const n of ["PROC-REP-056", "PROC-REP-046", "PROC-REP-047"]) assert.ok(!o.includes(n), `${id} no recorre ${n}`);
  }
  const hp3 = order(scenario("HP-REP-003"));
  assert.deepEqual(hp3.slice(hp3.indexOf("PROC-REP-045"), hp3.indexOf("PROC-REP-045") + 4), ["PROC-REP-045", "PROC-REP-055", "PROC-REP-050", "PROC-REP-060"]);
});

check("trazabilidad: 056 pertenece a FEAT-REP-002, cita BR-REP-027/028/031 y cada Scenario nuevo declara solo aristas reales", () => {
  const features = loadYaml<{ features: { id: string; process_nodes: string[]; business_rules: string[] }[] }>("business/features/repair-management-features-v1.4.yaml").features;
  const owners = features.filter((f) => f.process_nodes.includes("PROC-REP-056")).map((f) => f.id);
  assert.deepEqual(owners, ["FEAT-REP-002"]);
  const f2 = features.find((f) => f.id === "FEAT-REP-002");
  for (const r of node("PROC-REP-056")?.rules ?? []) assert.ok(f2?.business_rules.includes(r), `FEAT-REP-002 declara ${r}`);
  assert.deepEqual(node("PROC-REP-056")?.rules, ["BR-REP-027", "BR-REP-028", "BR-REP-031"]);
  const real = new Set(model.edges.map((e) => edgeKey(e.from, e.condition, e.to)));
  for (const id of ["VAR-REP-001", "VAR-REP-004", "VAR-REP-027", "VAR-REP-036"]) {
    for (const st of scenario(id).steps.filter(isProcessEdgeStep)) assert.ok(real.has(edgeKey(st.from, st.condition, st.to)), `${id}: ${st.from} -> ${st.to}`);
  }
});

if (failures > 0) {
  console.log(`\nFAILED: ${failures} test(s) failed.`);
  process.exit(1);
}
console.log("\nOK: iteracion 10 - todas las verificaciones de la decision del cliente pasaron.");
