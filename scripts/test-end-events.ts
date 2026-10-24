/**
 * End events per path (DC02). The functional validator copied from
 * rt-rma-app accepts any end node of the process for a Happy Path, because
 * V1.4 has two of them: EVT-REP-999, the end of a Repair Order, and
 * EVT-REP-998, a warranty intake that is not admitted (no Order is
 * created). This test keeps the Happy Path guarantee and tells the two ends
 * apart:
 *
 *   1. V1.4 declares exactly EVT-REP-998 and EVT-REP-999 as end nodes; V1.3
 *      (history) only EVT-REP-999.
 *   2. V1.4: EVT-REP-999 is reached only from PROC-REP-268 [Sin saldo a
 *      favor pendiente] and EVT-REP-998 only from PROC-REP-036 [Vencida, sin
 *      excepcion].
 *   3. The three Happy Paths end in EVT-REP-999, in V1.4 and in V1.3.
 *   4. Every Scenario that ends in an end node arrives through that end's
 *      edge; only VAR-REP-038 ends in EVT-REP-998, and never a Happy Path.
 *
 * Run: npm run test:end-events
 */
import assert from "node:assert/strict";
import { loadYaml, type ProcessModel } from "./lib/process-model";
import { isProcessEdgeStep, type Scenario, type ScenarioModel } from "./lib/scenario-model";

const HAPPY_PATHS = ["HP-REP-001", "HP-REP-002", "HP-REP-003"];
const ORDER_END = "EVT-REP-999";
const NOT_ADMITTED_END = "EVT-REP-998";

const load = (revision: string) => ({
  process: loadYaml<ProcessModel>(`business/processes/repair-management-${revision}.yaml`),
  scenarios: loadYaml<ScenarioModel>(`business/scenarios/repair-management-scenarios-${revision}.yaml`).scenarios,
});
const v14 = load("v1.4");
const v13 = load("v1.3");

const endNodes = (model: ProcessModel): string[] => model.nodes.filter((n) => n.type === "end").map((n) => n.id).sort();
const lastEdge = (s: Scenario) => s.steps.filter(isProcessEdgeStep).at(-1);
const into = (model: ProcessModel, to: string): string[] =>
  model.edges.filter((e) => e.to === to).map((e) => `${e.from}::${e.condition ?? ""}`);

const cases: [string, () => void][] = [
  [
    "1: V1.4 tiene dos fines (998 y 999); V1.3 solo 999",
    () => {
      assert.deepEqual(endNodes(v14.process), [NOT_ADMITTED_END, ORDER_END]);
      assert.deepEqual(endNodes(v13.process), [ORDER_END]);
    },
  ],
  [
    "2: V1.4 llega a 999 solo desde 268 [Sin saldo a favor pendiente] y a 998 solo desde 036 [Vencida, sin excepcion]",
    () => {
      assert.deepEqual(into(v14.process, ORDER_END), ["PROC-REP-268::Sin saldo a favor pendiente"]);
      assert.deepEqual(into(v14.process, NOT_ADMITTED_END), ["PROC-REP-036::Vencida, sin excepcion"]);
    },
  ],
  [
    "3: los tres Happy Paths terminan en EVT-REP-999 en V1.4 y en V1.3",
    () => {
      for (const { scenarios } of [v14, v13]) {
        for (const id of HAPPY_PATHS) {
          const s = scenarios.find((x) => x.id === id);
          assert.ok(s, `existe ${id}`);
          assert.equal(s.type, "HAPPY_PATH", id);
          assert.equal(lastEdge(s)?.to, ORDER_END, `${id} termina en ${ORDER_END}`);
        }
        assert.deepEqual(scenarios.filter((s) => s.type === "HAPPY_PATH").map((s) => s.id).sort(), HAPPY_PATHS);
      }
    },
  ],
  [
    "4: cada Scenario que termina en un fin llega por la arista de ese fin; solo VAR-REP-038 termina en 998",
    () => {
      const notAdmitted: string[] = [];
      for (const s of v14.scenarios) {
        const edge = lastEdge(s);
        if (edge?.to === ORDER_END) assert.equal(edge.from, "PROC-REP-268", s.id);
        if (edge?.to === NOT_ADMITTED_END) {
          assert.equal(`${edge.from}::${edge.condition ?? ""}`, "PROC-REP-036::Vencida, sin excepcion", s.id);
          assert.notEqual(s.type, "HAPPY_PATH", `${s.id}: un Happy Path no termina en ${NOT_ADMITTED_END}`);
          notAdmitted.push(s.id);
        }
      }
      assert.deepEqual(notAdmitted, ["VAR-REP-038"]);
    },
  ],
];

let failures = 0;
for (const [name, fn] of cases) {
  try {
    fn();
    console.log(`  OK   ${name}`);
  } catch (error) {
    failures += 1;
    console.log(`  FAIL ${name}`);
    console.log(`       ${(error as Error).message.split("\n").slice(0, 6).join("\n       ")}`);
  }
}
if (failures > 0) {
  console.log(`\nFAILED: ${failures} end-event test(s) failed.`);
  process.exit(1);
}
console.log(`\nOK: all ${cases.length} end-event tests passed.`);
