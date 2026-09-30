/**
 * Synthetic (in-memory) tests for checkGlobalConsistency().
 * Run: tsx scripts/test-traceability-global.ts
 */
import assert from "node:assert/strict";
import {
  checkBusinessIdentity,
  checkGlobalConsistency,
  type BusinessCatalog,
  type TraceItem,
} from "./lib/traceability-global";

const A = "traceability/a.yaml";
const B = "traceability/b.yaml";
const proc = (extra: Record<string, unknown> = {}): TraceItem => ({
  id: "PROC-REP-212",
  type: "process_node",
  name: "¿Iniciar un Detalle de reparacion?",
  ...extra,
});
const code = (source: string): TraceItem => ({ id: "CODE-REP-001", type: "code", name: "x", source });

const feat = (extra: Record<string, unknown> = {}): TraceItem => ({
  id: "FEAT-REP-004",
  type: "feature",
  name: "Gestion de prioridad, cola",
  ...extra,
});
const catalog = (): BusinessCatalog => ({
  feature: new Map([["FEAT-REP-004", "Gestion de prioridad, cola"]]),
});

const cases: [string, () => void][] = [
  [
    "A: unique ids pass",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [{ id: "FR-REP-001", type: "functional_requirement", name: "a" }] },
        { file: B, items: [{ id: "FR-REP-002", type: "functional_requirement", name: "b" }] },
      ]);
      assert.equal(r.collisions.length, 0);
      assert.equal(r.sharedIds, 0);
    },
  ],
  [
    "B: shared id differing only in contextual fields passes",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [proc({ in_scenario: true, coverage: "FULL", note: "x" })] },
        { file: B, items: [proc({ in_scenario: false, coverage: "PARTIAL", note: "y" })] },
      ]);
      assert.equal(r.collisions.length, 0);
      assert.equal(r.sharedIds, 1);
    },
  ],
  [
    "C: same id, different name fails",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [proc()] },
        { file: B, items: [proc({ name: "otro" })] },
      ]);
      assert.equal(r.collisions.length, 1);
      assert.deepEqual(r.collisions[0].occurrences[0].differing, ["name"]);
    },
  ],
  [
    "D: same id, different type fails",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [proc()] },
        { file: B, items: [proc({ type: "business_rule" })] },
      ]);
      assert.equal(r.collisions.length, 1);
    },
  ],
  [
    "E: same CODE id, different source fails",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [code("app/a.py")] },
        { file: B, items: [code("app/b.py")] },
      ]);
      assert.equal(r.collisions.length, 1);
      assert.deepEqual(r.collisions[0].occurrences[0].differing, ["source"]);
    },
  ],
  [
    "F: identical id in two scenarios passes",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [proc()] },
        { file: B, items: [proc()] },
      ]);
      assert.equal(r.collisions.length, 0);
      assert.equal(r.uniqueIds, 1);
    },
  ],
  [
    "source declared on only one side is not a collision",
    () => {
      const r = checkGlobalConsistency([
        { file: A, items: [code("app/a.py")] },
        { file: B, items: [{ id: "CODE-REP-001", type: "code", name: "x" }] },
      ]);
      assert.equal(r.collisions.length, 0);
    },
  ],
  [
    "G: traceability matching the source of truth passes",
    () => {
      const r = checkBusinessIdentity([{ file: A, items: [feat()] }], catalog());
      assert.equal(r.checked, 1);
      assert.equal(r.issues.length, 0);
    },
  ],
  [
    "H: same id, different name vs business fails",
    () => {
      const r = checkBusinessIdentity([{ file: A, items: [feat({ name: "Gestion de prioridad cola" })] }], catalog());
      assert.equal(r.nameMismatches, 1);
      assert.equal(r.issues[0].businessName, "Gestion de prioridad, cola");
    },
  ],
  [
    "I: business id missing from the source of truth fails",
    () => {
      const r = checkBusinessIdentity([{ file: A, items: [feat({ id: "FEAT-REP-999" })] }], catalog());
      assert.equal(r.missing, 1);
    },
  ],
  [
    "J: differing contextual fields pass",
    () => {
      const r = checkBusinessIdentity(
        [{ file: A, items: [feat({ status: "draft", coverage: "PARTIAL", in_scenario: true })] }],
        catalog(),
      );
      assert.equal(r.issues.length, 0);
    },
  ],
  [
    "technical artifacts are not looked up in business/",
    () => {
      const r = checkBusinessIdentity([{ file: A, items: [code("app/a.py")] }], catalog());
      assert.equal(r.checked, 0);
    },
  ],
];

for (const [name, fn] of cases) {
  fn();
  console.log(`PASS ${name}`);
}
console.log(`OK: ${cases.length} global traceability tests passed.`);
