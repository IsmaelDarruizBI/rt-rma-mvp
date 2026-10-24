/**
 * Dependency-free tests for AUD-V14-001: an OR with saldo a favor del cliente
 * must not get trapped in the cobro circuit (PROC-REP-265/266) nor finish /
 * be delivered without the money refund (PROC-REP-267, PROC-REP-268, BR-REP-038).
 *
 * Run: npm run test:commercial-closure:v1.4
 *
 * Three layers:
 *  A) graph invariants of the real V1.4 Process Graph (single gate to the end,
 *     exclusive exits of 265, context-labelled exits of 267, no cycle without a
 *     financial movement, cancellation / SIN_REPARACION / RT_INTERNO routes);
 *  B) the text of BR-REP-038 / BR-REP-017 and the Feature <-> node <-> rule
 *     traceability;
 *  C) a functional REPLAY of the V1.4 scenarios that carry money (HP-REP-001,
 *     VAR-REP-030..035): the Saldo is recomputed step by step with the approved
 *     formula and every routing decision of the scenario must be the one the
 *     rule dictates. It never reads the YAML as text, only the parsed models.
 */
import assert from "node:assert/strict";
import { scenarioOrigins } from "./lib/origin-filter";
import { loadYaml, type BusinessRule, type ProcessModel } from "./lib/process-model";
import { isFunctionalActionStep, isProcessEdgeStep, type Scenario, type ScenarioModel } from "./lib/scenario-model";

const PROCESS_FILE = "business/processes/repair-management-v1.4.yaml";
const RULES_FILE = "business/rules/business-rules-v1.4.yaml";
const FEATURES_FILE = "business/features/repair-management-features-v1.4.yaml";
const SCENARIOS_FILE = "business/scenarios/repair-management-scenarios-v1.4.yaml";

interface FeatureLite {
  id: string;
  process_nodes?: string[];
  business_rules?: string[];
}

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

const model = loadYaml<ProcessModel>(PROCESS_FILE);
const rules = loadYaml<{ rules: BusinessRule[] }>(RULES_FILE).rules;
const features = loadYaml<{ features: FeatureLite[] }>(FEATURES_FILE).features;
const scenarios = loadYaml<ScenarioModel>(SCENARIOS_FILE).scenarios;

const node = (id: string) => model.nodes.find((n) => n.id === id);
const nodeText = (id: string): string => flat(node(id)?.description);
const rule = (id: string): string => flat(rules.find((r) => r.id === id)?.description);
const scenario = (id: string): Scenario => {
  const s = scenarios.find((x) => x.id === id);
  assert.ok(s, `existe ${id}`);
  return s;
};
function flat(text: string | undefined): string {
  return (text ?? "").replace(/\s+/g, " ").trim();
}
const out = (from: string): string[] => model.edges.filter((e) => e.from === from).map((e) => `${e.condition ?? ""}->${e.to}`).sort();
const into = (to: string): string[] => model.edges.filter((e) => e.to === to).map((e) => `${e.from}::${e.condition ?? ""}`).sort();
const edgeSteps = (s: Scenario) => s.steps.filter(isProcessEdgeStep);
const traversed = (s: Scenario): Set<string> => {
  const nodes = new Set<string>();
  for (const step of edgeSteps(s)) {
    nodes.add(step.from);
    nodes.add(step.to);
  }
  return nodes;
};
const fact = (s: Scenario, key: string): unknown => s.facts.find((f) => f.key === key)?.value;
const expectedOf = (s: Scenario, key: string): unknown => s.expected.find((f) => f.key === key)?.value;

const GATE = "PROC-REP-268";
const REFUND = "PROC-REP-267";
const CHECKIN = "PROC-REP-269"; // consolidacion V1.4: entrega bloqueada hasta registrar el check-in (BR-REP-045)
const COMMERCIAL_NODES = ["PROC-REP-220", "PROC-REP-250", "PROC-REP-260", "PROC-REP-265", "PROC-REP-266", "PROC-REP-280"];

/**
 * PROC-REP-267 is shared by the delivery gate (265) and the pre-end gate (268):
 * its exit "Devolucion registrada, validar ..." depends on where it was entered
 * (context-labelled exit idiom, like PROC-REP-270). Pure topological reachability
 * crosses contexts; this traversal honours the labelled exit.
 */
function reachableInContext(start: string): Set<string> {
  const seen = new Set<string>();
  const visited = new Set<string>();
  const queue: Array<{ id: string; prev: string }> = [{ id: start, prev: "" }];
  while (queue.length > 0) {
    const { id, prev } = queue.shift() as { id: string; prev: string };
    const state = `${id}<${prev}`;
    if (visited.has(state)) continue;
    visited.add(state);
    seen.add(id);
    for (const e of model.edges.filter((edge) => edge.from === id)) {
      if (id === REFUND && (e.to === "PROC-REP-265") !== (prev === "PROC-REP-265")) continue;
      queue.push({ id: e.to, prev: id });
    }
  }
  return seen;
}

/** The approved formula: Saldo = Total final de la OR - Pagos recibidos + Devoluciones realizadas. */
function saldo(total: number, payments: number[], refunds: number[]): number {
  const sum = (xs: number[]): number => xs.reduce((a, b) => a + b, 0);
  return total - sum(payments) + sum(refunds);
}

/**
 * Routing of PROC-REP-265 for an origin with commercial circuit (CLIENTE_EXTERNO). Consolidation V1.4
 * (UAT-009, BR-REP-045): with the Saldo at 0, an Order with completed work also needs the check-in.
 */
function route265(balance: number, checkinPending = false): { to: string; condition: string } {
  if (balance > 0) return { to: "PROC-REP-266", condition: "No, saldo pendiente de cobro" };
  if (balance === 0) return checkinPending ? { to: CHECKIN, condition: "Saldo en 0, falta el check-in" } : { to: "PROC-REP-280", condition: "Si" };
  return { to: REFUND, condition: "No, saldo a favor del cliente" };
}

/** Executable restatement of the BR-REP-038 refund constraints, used only by the replay. */
class RefundLedger {
  readonly refunds: Array<{ ref: string; amount: number }> = [];
  constructor(readonly total: number, readonly payments: readonly number[]) {}
  get balance(): number {
    return saldo(this.total, [...this.payments], this.refunds.map((r) => r.amount));
  }
  register(ref: string, amount: number): "REGISTERED" | "REJECTED_DUPLICATE" | "REJECTED_NOT_POSITIVE" | "REJECTED_OVER_CREDIT" {
    if (this.refunds.some((r) => r.ref === ref)) return "REJECTED_DUPLICATE"; // no double imputation
    if (!(amount > 0)) return "REJECTED_NOT_POSITIVE"; // a refund is a positive amount, never a negative payment
    if (amount > -this.balance) return "REJECTED_OVER_CREDIT"; // no refund above the pending credit
    this.refunds.push({ ref, amount });
    return "REGISTERED";
  }
}

console.log("\nAUD-V14-001 - saldo a favor del cliente y devolucion de dinero (V1.4)\n");

// ------------------------------------------------------------------ A) graph
console.log("A) Process Graph\n");

check("la formula aprobada produce el ejemplo: Total 0, anticipo 5.000 -> -5.000 -> -2.000 -> 0", () => {
  assert.equal(saldo(0, [5000], []), -5000);
  assert.equal(saldo(0, [5000], [3000]), -2000);
  assert.equal(saldo(0, [5000], [3000, 2000]), 0);
  assert.equal(saldo(10000, [4000], []), 6000, "saldo positivo: sigue el cobro");
  assert.equal(saldo(5000, [5000], []), 0, "saldo cero: sin movimientos nuevos");
});

check("EVT-REP-999 solo se alcanza desde la verificacion previa al fin (PROC-REP-268)", () => {
  assert.deepEqual(into("EVT-REP-999"), [`${GATE}::Sin saldo a favor pendiente`]);
});

check("ningun camino desde un evento de inicio llega al fin sin pasar por PROC-REP-268", () => {
  const hasIncoming = new Set(model.edges.map((e) => e.to));
  const starts = model.nodes.filter((n) => (n.type === "start" || n.type === "event") && !hasIncoming.has(n.id)).map((n) => n.id);
  assert.ok(starts.length >= 3, `eventos de inicio detectados: ${starts.join(", ")}`);
  const seen = new Set<string>();
  const queue = [...starts];
  while (queue.length > 0) {
    const id = queue.shift() as string;
    if (seen.has(id) || id === GATE) continue; // 268 removed from the graph
    seen.add(id);
    for (const e of model.edges.filter((edge) => edge.from === id)) queue.push(e.to);
  }
  assert.ok(!seen.has("EVT-REP-999"), "sin 268 el fin es inalcanzable");
});

check("268 y 267: salidas exactas; 267 rotula su salida por contexto (entrega o fin de Orden)", () => {
  assert.deepEqual(out(GATE), ["Saldo a favor del cliente pendiente de devolver->PROC-REP-267", "Sin saldo a favor pendiente->EVT-REP-999"].sort());
  assert.deepEqual(out(REFUND), ["Devolucion registrada, validar entrega->PROC-REP-265", "Devolucion registrada, validar fin de Orden->PROC-REP-268"].sort());
  assert.deepEqual(into(REFUND), ["PROC-REP-265::No, saldo a favor del cliente", "PROC-REP-268::Saldo a favor del cliente pendiente de devolver"].sort());
  assert.equal(node(REFUND)?.actor, "ACT-RECEP");
  assert.equal(node(GATE)?.type, "decision");
});

check("265 tiene cuatro salidas excluyentes (V1.4 consolidada suma el check-in) y el saldo a favor nunca entra al circuito de cobro (266)", () => {
  assert.deepEqual(out("PROC-REP-265"), [
    "No, saldo a favor del cliente->PROC-REP-267",
    "No, saldo pendiente de cobro->PROC-REP-266",
    "Saldo en 0, falta el check-in->PROC-REP-269",
    "Si->PROC-REP-280",
  ].sort());
  assert.deepEqual(into(CHECKIN), ["PROC-REP-265::Saldo en 0, falta el check-in"], "269 solo recibe la entrega bloqueada por check-in");
  assert.deepEqual(out(CHECKIN), ["Revalidar->PROC-REP-265"]);
  assert.deepEqual(into("PROC-REP-266"), ["PROC-REP-265::No, saldo pendiente de cobro"], "266 solo recibe saldo pendiente de cobro");
  assert.deepEqual(out("PROC-REP-266"), ["Revalidar->PROC-REP-265"]);
  assert.deepEqual(into("PROC-REP-280"), ["PROC-REP-265::Si"], "el comprobante final y la entrega solo se habilitan con 265 aprobado (Saldo = 0)");
});

check("no hay ciclos sin accion financiera: todo ciclo entre 265/266/267/268 pasa por un nodo que exige un movimiento real", () => {
  const set = ["PROC-REP-265", "PROC-REP-266", REFUND, GATE, CHECKIN];
  const cycles: string[][] = [];
  const dfs = (start: string, current: string, path: string[]): void => {
    for (const e of model.edges.filter((edge) => edge.from === current && set.includes(edge.to))) {
      if (e.to === start) cycles.push([...path]);
      else if (set.indexOf(e.to) > set.indexOf(start) && !path.includes(e.to)) dfs(start, e.to, [...path, e.to]);
    }
  };
  for (const s of set) dfs(s, s, [s]);
  assert.ok(cycles.length >= 3, `ciclos detectados: ${cycles.map((c) => c.join(">")).join(" | ")}`);
  for (const cycle of cycles) {
    assert.ok(cycle.includes("PROC-REP-266") || cycle.includes(REFUND) || cycle.includes(CHECKIN), `el ciclo ${cycle.join(">")} exige un pago (266), una devolucion (267) o el check-in (269)`);
  }
  assert.match(nodeText(REFUND), /Cada pasada por este nodo exige un movimiento real/);
  assert.match(nodeText("PROC-REP-266"), /pago/i);
});

check("cancelaciones y desistimientos (306, 211 cancelado, 271) llegan a la verificacion de saldo y nunca a la entrega comercial", () => {
  const exits = [
    ...model.edges.filter((e) => e.from === "PROC-REP-211" && /Todos cancelados/.test(e.condition ?? "")),
    ...model.edges.filter((e) => e.from === "PROC-REP-306"),
    ...model.edges.filter((e) => e.from === "PROC-REP-271"),
  ];
  assert.equal(exits.length, 3 + 3 + 2);
  for (const e of exits) {
    const reach = reachableInContext(e.to);
    assert.ok(reach.has(GATE), `${e.from} -> ${e.to} [${e.condition}] llega a 268`);
    for (const bad of COMMERCIAL_NODES) assert.ok(!reach.has(bad), `${e.from} -> ${e.to} no alcanza ${bad}`);
  }
  assert.ok(!model.edges.some((e) => e.to === "EVT-REP-999" && e.from !== GATE), "ninguna cancelacion llega directo al fin");
});

check("SIN_REPARACION (069) conserva su ruta de cierre al cliente y alcanza la validacion comercial de 265 y el registro de la devolucion", () => {
  assert.deepEqual(out("PROC-REP-069"), ["->PROC-REP-250"]);
  assert.ok(out("PROC-REP-250").includes("Si->PROC-REP-260"));
  assert.deepEqual(out("PROC-REP-260"), ["->PROC-REP-265"]);
  const reach = reachableInContext("PROC-REP-069");
  for (const id of ["PROC-REP-265", REFUND, "PROC-REP-280", "PROC-REP-270", GATE, "EVT-REP-999"]) assert.ok(reach.has(id), `069 alcanza ${id}`);
});

check("RT_INTERNO (290 -> 270 -> 268) no pasa por cobro ni devolucion de dinero: la verificacion es trivial", () => {
  const reach = reachableInContext("PROC-REP-290");
  for (const id of ["PROC-REP-270", GATE, "EVT-REP-999"]) assert.ok(reach.has(id), `290 alcanza ${id}`);
  for (const bad of ["PROC-REP-265", "PROC-REP-266", "PROC-REP-280"]) assert.ok(!reach.has(bad), `290 no alcanza ${bad}`);
  assert.match(nodeText(GATE), /RT_INTERNO, RMA_GARANTIA_REPARACION, RT_GARANTIA_VENTA\) no existen Pagos/);
});

check("la devolucion fisica (270) y la de dinero (267) son dimensiones independientes", () => {
  assert.deepEqual(out("PROC-REP-270"), ["->PROC-REP-268"], "la devolucion fisica no finaliza la Orden: pasa por la verificacion de saldo");
  assert.match(nodeText(REFUND), /Es independiente de la\s+devolucion FISICA del equipo/);
  assert.match(nodeText(GATE), /independiente de la devolucion fisica del equipo/);
  assert.match(nodeText("PROC-REP-270"), /independientes/);
});

// ----------------------------------------------------- B) rules & traceability
console.log("\nB) Reglas y trazabilidad\n");

check("BR-REP-038: formula aprobada, devolucion obligatoria antes de entregar o cerrar, ejemplo y sin pago negativo", () => {
  const r = rule("BR-REP-038");
  assert.match(r, /Saldo = Total final de la OR - Pagos recibidos \+ Devoluciones realizadas/);
  assert.match(r, /es OBLIGATORIO registrar la devolucion de dinero correspondiente antes de permitir la entrega o el cierre comercial/);
  assert.match(r, /haber identificado el saldo a favor no habilita por si solo ninguna de las dos cosas/);
  assert.match(r, /no se borran ni modifican retroactivamente los Pagos originales/);
  assert.match(r, /una devolucion NO se representa como un Pago de importe negativo/);
  assert.match(r, /Saldo > 0, cobro pendiente/);
  assert.match(r, /Saldo = 0, se puede continuar/);
  assert.match(r, /Saldo < 0, se registra una devolucion/);
  assert.match(r, /devolucion parcial mantiene el saldo a favor remanente pendiente y la Orden no se entrega/);
  assert.match(r, /devolucion total deja Saldo = 0 y se revalida la condicion de entrega/);
  assert.match(r, /Total \$0, anticipo \$5\.000, devolucion \$0 -> Saldo -5\.000; tras devolver \$3\.000 -> -2\.000 \(no entregable\); tras otros \$2\.000 -> 0/);
});

check("BR-REP-038: registro minimo, historial, sin sobredevolucion, sin doble imputacion y devolucion realizada vs intencion", () => {
  const r = rule("BR-REP-038");
  for (const field of ["identificador unico del movimiento", "OR relacionada", "importe positivo devuelto", "medio de devolucion", "usuario responsable", "fecha/hora", "referencia de la operacion", "motivo"]) {
    assert.ok(r.includes(field), `registro minimo incluye ${field}`);
  }
  assert.match(r, /historial completo de devoluciones parciales y totales/);
  assert.match(r, /No se admite una devolucion superior al saldo a favor pendiente \(salvo una regla adicional expresamente aprobada\)/);
  assert.match(r, /no se computa dos veces por reintentos o reingresos/);
  assert.match(r, /Solo una devolucion registrada y efectivamente realizada modifica el Saldo; una intencion o solicitud pendiente no/);
  assert.match(r, /No hay ciclos sin accion financiera/);
});

check("BR-REP-038: casos, independencia fisica/dinero, origenes sin circuito comercial y pendientes de negocio", () => {
  const r = rule("BR-REP-038");
  assert.match(r, /revision sin reparacion con anticipo/);
  assert.match(r, /cancelacion de trabajos con anticipos/);
  assert.match(r, /varios Detalles con algunos completos y otros cancelados \(se devuelve unicamente el excedente/);
  assert.match(r, /la devolucion de dinero no es la devolucion fisica del equipo ni la custodia/);
  assert.match(r, /Origenes sin circuito comercial \(RT_INTERNO, RMA_GARANTIA_REPARACION, RT_GARANTIA_VENTA\)/);
  assert.match(r, /un saldo a favor en ellos no esta definido y se documenta como pendiente funcional/);
  // DC12C (consolidacion V1.4) define quien registra; el catalogo de medios sigue pendiente
  assert.match(r, /registran devoluciones por defecto Administracion o Recepcion, con permiso configurable/);
  assert.match(r, /el catalogo de medios de devolucion sigue pendiente/);
  // BR-REP-014 ya no esta congelada (DC07): los reembolsos de una Orden CANCELADA son saldo a favor
  assert.match(r, /Relacion con BR-REP-014: los reembolsos de pagos ya realizados cuando la Orden termina CANCELADA se tratan como saldo a favor/);
  assert.match(r, /plazo o abandono si el cliente no retira el dinero/);
});

check("BR-REP-017 conserva el texto V1.3 y agrega la formula con devoluciones; 267/268 citan BR-REP-038", () => {
  const r = rule("BR-REP-017");
  assert.match(r, /Saldo = Total final de la OR - Pagos recibidos \+ Devoluciones realizadas/);
  assert.match(r, /Saldo < 0 \(saldo a favor del cliente\) -> registro de la devolucion de dinero \(PROC-REP-267\), nunca por el circuito de cobro/);
  for (const id of [REFUND, GATE]) assert.ok((node(id)?.rules ?? []).includes("BR-REP-038"), `${id} cita BR-REP-038`);
});

check("trazabilidad Feature <-> nodo <-> regla: FEAT-REP-007 posee 267, FEAT-REP-008 posee 268 y ambas declaran BR-REP-038", () => {
  const f7 = features.find((f) => f.id === "FEAT-REP-007");
  const f8 = features.find((f) => f.id === "FEAT-REP-008");
  assert.ok(f7?.process_nodes?.includes(REFUND) && !f7.process_nodes.includes(GATE));
  assert.ok(f8?.process_nodes?.includes(GATE) && !f8.process_nodes.includes(REFUND));
  assert.ok(f7?.business_rules?.includes("BR-REP-038"));
  assert.ok(f8?.business_rules?.includes("BR-REP-038"));
  const owners = (id: string): string[] => features.filter((f) => f.process_nodes?.includes(id)).map((f) => f.id);
  assert.deepEqual(owners(REFUND), ["FEAT-REP-007"]);
  assert.deepEqual(owners(GATE), ["FEAT-REP-008"]);
});

// ------------------------------------------------------- C) functional replay
console.log("\nC) Recorrido funcional con saldo (replay de Scenarios)\n");

/** Money inputs of a scenario, read from its own facts. */
function moneyOf(s: Scenario): { total: number; initialPayments: number[]; paymentOnAction: number; refunds: number[] } {
  const num = (key: string): number | undefined => {
    const v = fact(s, key);
    return typeof v === "number" ? v : undefined;
  };
  const refundAmount = num("refund_amount");
  const first = num("first_refund_amount");
  const second = num("second_refund_amount");
  const before = num("balance_before_refund");
  return {
    total: num("final_total") ?? 0,
    initialPayments: num("advance_payments_total") !== undefined ? [num("advance_payments_total") as number] : [],
    paymentOnAction: num("advance_payment_amount") ?? num("deposit_amount") ?? 0,
    refunds: first !== undefined ? [first, second ?? 0] : refundAmount !== undefined ? [refundAmount] : before !== undefined ? [-before] : [],
  };
}

/** Replays the scenario steps with a ledger and returns the visible trace; every decision is asserted. */
function replay(s: Scenario): { ledger: RefundLedger; balanceAtFirst267: number | undefined; balanceAfterFirstRefund: number | undefined; path: string[] } {
  const money = moneyOf(s);
  const payments = [...money.initialPayments];
  let ledger = new RefundLedger(money.total, payments);
  const refundQueue = [...money.refunds];
  const path: string[] = [];
  let refundsAtLastEntryTo267 = -1;
  let checkinRegistered = fact(s, "checkin_required_for_delivery") !== true;
  let balanceAtFirst267: number | undefined;
  let balanceAfterFirstRefund: number | undefined;
  const rebuild = (): void => {
    const keep = ledger.refunds;
    ledger = new RefundLedger(money.total, payments);
    for (const r of keep) ledger.refunds.push(r);
  };
  for (const step of s.steps) {
    if (isFunctionalActionStep(step)) {
      if (/^Registrar (anticipo|sena|pago)/.test(step.name)) {
        payments.push(money.paymentOnAction);
        rebuild();
      } else if (/^Anular pago/.test(step.name)) {
        // DC10: the voided Pago is kept as voided and stops counting for the Saldo
        assert.ok(payments.length > 0, `${s.id}: hay un Pago que anular`);
        payments.pop();
        rebuild();
      } else if (/^Registrar check-in/.test(step.name)) {
        checkinRegistered = true;
      } else if (/^Registrar devolucion/.test(step.name)) {
        const amount = refundQueue.shift();
        assert.ok(amount !== undefined, `${s.id}: hay un importe de devolucion para "${step.name}"`);
        const credit = -ledger.balance;
        assert.ok(credit > 0, `${s.id}: solo se devuelve si hay saldo a favor (Saldo ${ledger.balance})`);
        assert.equal(ledger.register(`REF-${ledger.refunds.length + 1}`, amount as number), "REGISTERED", `${s.id}: devolucion de ${amount} sobre ${credit} pendiente`);
        if (ledger.refunds.length === 1) balanceAfterFirstRefund = ledger.balance;
      } else if (/^Rechazar devolucion superior/.test(step.name)) {
        const attempt = fact(s, "over_credit_refund_attempt") as number;
        const before = ledger.balance;
        assert.equal(ledger.register("REF-X", attempt), "REJECTED_OVER_CREDIT", `${s.id}: ${attempt} supera el credito pendiente ${-before}`);
        assert.equal(ledger.balance, before, `${s.id}: un rechazo no modifica el Saldo`);
      } else if (/^Rechazar reingreso/.test(step.name)) {
        const before = ledger.balance;
        assert.equal(ledger.register("REF-1", ledger.refunds[0]?.amount ?? 1), "REJECTED_DUPLICATE", `${s.id}: la misma referencia no se imputa dos veces`);
        assert.equal(ledger.balance, before, `${s.id}: el reingreso no modifica el Saldo`);
      }
      continue;
    }
    if (!isProcessEdgeStep(step)) continue;
    path.push(`${step.from}>${step.to}`);
    const balance = ledger.balance;
    if (step.from === "PROC-REP-265") {
      const expected = route265(balance, !checkinRegistered);
      assert.equal(step.to, expected.to, `${s.id}: con Saldo ${balance}, 265 debe ir a ${expected.to}`);
      assert.equal(step.condition, expected.condition, `${s.id}: con Saldo ${balance}, la condicion de 265 es "${expected.condition}"`);
    }
    if (step.to === REFUND) {
      assert.ok(balance < 0, `${s.id}: solo se llega al registro de devolucion con saldo a favor (Saldo ${balance})`);
      refundsAtLastEntryTo267 = ledger.refunds.length;
      balanceAtFirst267 ??= balance;
    }
    if (step.from === REFUND) {
      assert.ok(ledger.refunds.length > refundsAtLastEntryTo267, `${s.id}: 267 solo se abandona tras una devolucion realmente registrada (sin ciclo vacio)`);
    }
    if (step.from === GATE && step.to === REFUND) assert.ok(balance < 0, `${s.id}: 268 deriva a 267 solo con saldo a favor`);
    if (step.from === GATE && step.to === "EVT-REP-999") assert.equal(balance, 0, `${s.id}: la Orden finaliza con Saldo ${balance}`);
    if (step.from === "PROC-REP-280") assert.equal(balance, 0, `${s.id}: no se genera comprobante final ni se entrega con Saldo ${balance}`);
    if (step.to === "PROC-REP-266") assert.ok(balance > 0, `${s.id}: el circuito de cobro solo atiende Saldo > 0`);
  }
  assert.equal(refundQueue.length, 0, `${s.id}: todas las devoluciones previstas se registraron`);
  return { ledger, balanceAtFirst267, balanceAfterFirstRefund, path };
}

check("BLOCKER VAR-REP-030: revision sin reparacion con anticipo de $5.000 -> -5.000 -> devolucion -> 0 -> devolucion fisica -> fin", () => {
  const s = scenario("VAR-REP-030");
  const r = replay(s);
  assert.deepEqual(r.path, [
    "PROC-REP-068>PROC-REP-069",
    "PROC-REP-069>PROC-REP-250",
    "PROC-REP-250>PROC-REP-260",
    "PROC-REP-260>PROC-REP-265",
    "PROC-REP-265>PROC-REP-267",
    "PROC-REP-267>PROC-REP-265",
    "PROC-REP-265>PROC-REP-280",
    "PROC-REP-280>PROC-REP-270",
    "PROC-REP-270>PROC-REP-268",
    "PROC-REP-268>EVT-REP-999",
  ]);
  assert.equal(r.balanceAtFirst267, -5000);
  assert.equal(r.ledger.balance, 0);
  assert.deepEqual(r.ledger.refunds.map((x) => x.amount), [5000]);
  assert.equal(r.ledger.payments[0], 5000, "el anticipo original no se modifica");
  assert.ok(!traversed(s).has("PROC-REP-266"), "no usa el circuito de cobro");
  assert.equal(expectedOf(s, "refund_recorded_as_negative_payment"), false);
  assert.equal(expectedOf(s, "original_payment_preserved"), true);
  assert.equal(expectedOf(s, "final_balance"), 0);
  assert.equal(expectedOf(s, "equipment_return_registered"), true);
  assert.equal(expectedOf(s, "delivery_blocked_while_balance_negative"), true);
});

check("VAR-REP-031: varios Detalles (2 COMPLETO, 1 CANCELADO) -> solo se devuelve el excedente, en dos devoluciones parciales", () => {
  const s = scenario("VAR-REP-031");
  const r = replay(s);
  assert.equal(r.balanceAtFirst267, -10000);
  assert.equal(r.balanceAfterFirstRefund, expectedOf(s, "balance_after_first_refund"));
  assert.equal(r.balanceAfterFirstRefund, -4000);
  assert.equal(r.ledger.balance, 0);
  assert.deepEqual(r.ledger.refunds.map((x) => x.amount), [6000, 4000]);
  assert.equal(r.ledger.refunds.length, expectedOf(s, "refunds_registered"), "historial con ambas devoluciones");
  assert.equal(saldo(20000, [30000], [6000, 4000]), 0);
  const to265 = edgeSteps(s).filter((e) => e.from === "PROC-REP-265").map((e) => e.to);
  assert.deepEqual(to265, [REFUND, REFUND, "PROC-REP-280"], "tras la devolucion parcial 265 vuelve a derivar a 267 y no entrega (el check-in ya estaba registrado)");
  assert.equal(expectedOf(s, "delivery_allowed_with_partial_refund"), false);
  assert.equal(expectedOf(s, "refund_over_credit_accepted"), false);
  assert.equal(expectedOf(s, "refund_double_counted"), false);
});

check("VAR-REP-032: cancelacion con anticipo y equipo en custodia -> devolucion fisica (270) y la Orden NO finaliza hasta devolver el dinero", () => {
  const s = scenario("VAR-REP-032");
  const r = replay(s);
  const order = edgeSteps(s).flatMap((e) => [e.from, e.to]).filter((id, i, all) => i === 0 || id !== all[i - 1]);
  const at = (id: string): number => order.indexOf(id);
  assert.ok(at("PROC-REP-270") < at(GATE) && at(GATE) < at(REFUND) && at(REFUND) < at("EVT-REP-999"), `orden: ${order.join(" > ")}`);
  assert.equal(r.balanceAtFirst267, -8000);
  assert.equal(r.ledger.balance, 0);
  for (const bad of COMMERCIAL_NODES) assert.ok(!traversed(s).has(bad), `la Orden CANCELADA no recorre ${bad}`);
  assert.equal(expectedOf(s, "workflow_state"), "CANCELADA");
  assert.equal(expectedOf(s, "physical_return_replaces_refund"), false);
  assert.equal(expectedOf(s, "order_ended_before_refund"), false);
});

check("VAR-REP-033: desistimiento antes del comprobante con sena y sin equipo en custodia -> 211 -> 268 -> 267 -> 268 -> fin", () => {
  const s = scenario("VAR-REP-033");
  const r = replay(s);
  assert.equal(r.balanceAtFirst267, -3000);
  assert.equal(r.ledger.balance, 0);
  assert.ok(!traversed(s).has("PROC-REP-270"), "sin custodia no hay devolucion fisica");
  for (const bad of COMMERCIAL_NODES) assert.ok(!traversed(s).has(bad), `la Orden CANCELADA no recorre ${bad}`);
  assert.equal(expectedOf(s, "equipment_return_registered"), false);
  assert.equal(expectedOf(s, "refund_registered"), true);
});

check("VAR-REP-034: saldo cero con anticipo exacto -> sin cobro, sin devolucion y sin movimientos financieros nuevos", () => {
  const s = scenario("VAR-REP-034");
  const r = replay(s);
  assert.equal(r.ledger.balance, 0);
  assert.equal(r.ledger.refunds.length, 0);
  for (const bad of ["PROC-REP-266", REFUND]) assert.ok(!traversed(s).has(bad), `no recorre ${bad}`);
  assert.equal(expectedOf(s, "new_financial_movements"), false);
});

check("HP-REP-001 conserva el cobro de saldo positivo (265 -> 266 -> 265) y no recorre la devolucion de dinero", () => {
  const s = scenario("HP-REP-001");
  const edges = edgeSteps(s);
  assert.ok(edges.some((e) => e.from === "PROC-REP-265" && e.to === "PROC-REP-266" && e.condition === "No, saldo pendiente de cobro"));
  assert.ok(edges.some((e) => e.from === "PROC-REP-266" && e.to === "PROC-REP-265" && e.condition === "Revalidar"));
  assert.ok(!traversed(s).has(REFUND));
  assert.equal(expectedOf(s, "final_balance"), 0);
  assert.equal(edges.at(-1)?.from, GATE);
  assert.equal(edges.at(-1)?.to, "EVT-REP-999");
});

check("origenes sin circuito comercial: ningun Scenario de RT_INTERNO / RMA_GARANTIA_REPARACION cobra, devuelve dinero ni recorre 266/267", () => {
  const origins = scenarioOrigins(scenarios);
  const nonCommercial = scenarios.filter((s) => {
    const o = origins.get(s.id);
    return Array.isArray(o) && o.length > 0 && !o.includes("CLIENTE_EXTERNO");
  });
  assert.ok(nonCommercial.some((s) => s.id === "VAR-REP-035") && nonCommercial.some((s) => s.id === "HP-REP-002") && nonCommercial.some((s) => s.id === "HP-REP-003"));
  for (const s of nonCommercial) {
    for (const bad of ["PROC-REP-266", REFUND]) assert.ok(!traversed(s).has(bad), `${s.id} no recorre ${bad}`);
    const money = s.steps.filter(isFunctionalActionStep).filter((a) => /pago|anticipo|sena|devolucion de dinero|cobro/i.test(a.name));
    assert.deepEqual(money.map((a) => a.name), [], `${s.id} no registra pagos ni devoluciones`);
  }
  const s35 = scenario("VAR-REP-035");
  assert.equal(expectedOf(s35, "payment_registered"), false);
  assert.equal(expectedOf(s35, "refund_registered"), false);
  assert.equal(edgeSteps(s35).at(-2)?.to, GATE);
});

check("VAR-REP-040 (DC10): el Pago anulado se conserva y deja de contar; el Saldo vuelve a ser positivo y se cobra antes de entregar", () => {
  const s = scenario("VAR-REP-040");
  const r = replay(s);
  assert.equal(r.ledger.balance, 0);
  assert.ok(r.path.includes("PROC-REP-265>PROC-REP-266"), "tras la anulacion hay saldo pendiente de cobro");
  assert.ok(r.path.includes(`PROC-REP-265>${CHECKIN}`), "con el Saldo en 0 falta el check-in");
  assert.equal(expectedOf(s, "voided_payment_preserved"), true);
  assert.equal(expectedOf(s, "voided_payment_counts_in_balance"), false);
  assert.match(rule("BR-REP-017"), /el Pago nunca se borra, queda registrado como anulado/);
});

check("VAR-REP-041 (DC11): cortesia total con un anticipo deja saldo a favor; se devuelve antes de entregar, sin tocar el Pago ni el Ajuste", () => {
  const s = scenario("VAR-REP-041");
  const r = replay(s);
  assert.equal(r.balanceAtFirst267, -5000);
  assert.equal(r.ledger.balance, 0);
  assert.deepEqual(r.ledger.refunds.map((x) => x.amount), [5000]);
  const order = r.path;
  assert.ok(order.indexOf("PROC-REP-265>PROC-REP-267") < order.indexOf("PROC-REP-265>PROC-REP-280"), "la devolucion precede a la entrega");
  assert.equal(expectedOf(s, "delivery_allowed_before_refund"), false);
  assert.match(rule("BR-REP-016"), /Una cortesia total con Pagos\s*ya recibidos deja saldo a favor del cliente/);
});

check("los Scenarios con dinero respetan la formula y quedan consistentes con sus facts (sin saldo ni importes contradictorios)", () => {
  for (const id of ["VAR-REP-030", "VAR-REP-031", "VAR-REP-032", "VAR-REP-033", "VAR-REP-034", "VAR-REP-040", "VAR-REP-041"]) {
    const s = scenario(id);
    const m = moneyOf(s);
    const payments = m.initialPayments.length > 0 ? m.initialPayments : [m.paymentOnAction];
    const before = fact(s, "balance_before_refund");
    if (before !== undefined) assert.equal(saldo(m.total, payments, []), before, `${id}: Saldo antes de devolver`);
    assert.equal(saldo(m.total, payments, m.refunds), expectedOf(s, "final_balance"), `${id}: Saldo final`);
  }
});

if (failures > 0) {
  console.log(`\nFAILED: ${failures} test(s) failed.`);
  process.exit(1);
}
console.log("\nOK: AUD-V14-001 - todas las verificaciones de saldo a favor y devolucion de dinero pasaron.");
