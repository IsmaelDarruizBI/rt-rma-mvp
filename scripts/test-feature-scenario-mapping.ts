/**
 * Minimal, dependency-free test runner for
 * scripts/lib/feature-scenario-mapping.ts's deriveScenarioFeatures().
 *
 * No test framework exists yet in this repo (no jest/vitest/mocha in
 * package.json), and adding one just for this one helper would be
 * disproportionate. This script asserts against Node's built-in
 * `node:assert/strict`, exits non-zero on the first failure, and prints
 * "OK" on success - reproducible via `tsx scripts/test-feature-scenario-mapping.ts`,
 * no new dependency.
 *
 * Exercises the REAL V1.3 process + Features files (not a hand-built
 * fixture) so these tests fail immediately if the actual
 * shared_node_bindings in business/features/repair-management-features-v1.3.yaml
 * ever drift from the semantics they're supposed to encode - each
 * scenario below is a small synthetic PROCESS_EDGE-only Scenario, not the
 * full HP-REP-001.
 */
import assert from "node:assert/strict";
import { loadYaml, type ProcessModel } from "./lib/process-model";
import type { FeatureModel } from "./lib/feature-model";
import { deriveScenarioFeatures, findSharedNodes, summarizeSharedNodeBindings } from "./lib/feature-scenario-mapping";
import type { Scenario, ScenarioStep } from "./lib/scenario-model";

// Revision under test: `tsx scripts/test-feature-scenario-mapping.ts v1.4`
// (defaults to v1.3, so the existing command is unchanged).
const REVISION = process.argv[2] ?? "v1.3";
const PROCESS_FILE = `business/processes/repair-management-${REVISION}.yaml`;
const FEATURES_FILE = `business/features/repair-management-features-${REVISION}.yaml`;

function edgeStep(from: string, to: string, condition?: string): ScenarioStep {
  return condition ? { kind: "PROCESS_EDGE", from, to, condition } : { kind: "PROCESS_EDGE", from, to };
}

function makeScenario(steps: ScenarioStep[]): Scenario {
  return {
    id: "TEST-SCENARIO",
    name: "Synthetic test scenario",
    type: "HAPPY_PATH",
    scope: "E2E",
    status: "draft",
    source_process: { id: "PROC-REP", version: "1.3" },
    description: "Synthetic scenario for deriveScenarioFeatures() tests, not a real Scenario.",
    facts: [],
    steps,
    expected: [],
  };
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

function main(): void {
  const featuresModel = loadYaml<FeatureModel>(FEATURES_FILE);
  // Loaded only to fail loudly if the fixture files themselves ever go missing/malformed.
  loadYaml<ProcessModel>(PROCESS_FILE);

  console.log(`Testing deriveScenarioFeatures() against ${FEATURES_FILE}\n`);

  // A) PROC-REP-210 -> PROC-REP-211 activates FEAT-REP-005, not FEAT-REP-006/009.
  check("A) 210->211 activates FEAT-REP-005 only (of the 211 owners)", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(featuresModel, makeScenario([edgeStep("PROC-REP-210", "PROC-REP-211")]));
    assert.ok(activeFeatureIds.includes("FEAT-REP-005"), "expected FEAT-REP-005 active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-006"), "expected FEAT-REP-006 NOT active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-009"), "expected FEAT-REP-009 NOT active");
  });

  // B) PROC-REP-235 -> PROC-REP-211 activates FEAT-REP-006.
  check("B) 235->211 activates FEAT-REP-006", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(featuresModel, makeScenario([edgeStep("PROC-REP-235", "PROC-REP-211")]));
    assert.ok(activeFeatureIds.includes("FEAT-REP-006"), "expected FEAT-REP-006 active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-005"), "expected FEAT-REP-005 NOT active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-009"), "expected FEAT-REP-009 NOT active");
  });

  // C) PROC-REP-300 -> PROC-REP-211 activates FEAT-REP-009.
  check("C) 300->211 activates FEAT-REP-009", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(featuresModel, makeScenario([edgeStep("PROC-REP-300", "PROC-REP-211")]));
    assert.ok(activeFeatureIds.includes("FEAT-REP-009"), "expected FEAT-REP-009 active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-005"), "expected FEAT-REP-005 NOT active");
    assert.ok(!activeFeatureIds.includes("FEAT-REP-006"), "expected FEAT-REP-006 NOT active");
  });

  // D) PROC-REP-305 -> PROC-REP-211 activates FEAT-REP-009.
  check("D) 305->211 activates FEAT-REP-009", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(featuresModel, makeScenario([edgeStep("PROC-REP-305", "PROC-REP-211")]));
    assert.ok(activeFeatureIds.includes("FEAT-REP-009"), "expected FEAT-REP-009 active");
  });

  // E) Traversing PROC-REP-070 activates FEAT-REP-002 and FEAT-REP-007 (both ALWAYS).
  check("E) touching PROC-REP-070 activates FEAT-REP-002 + FEAT-REP-007", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(
      featuresModel,
      makeScenario([edgeStep("PROC-REP-045", "PROC-REP-070", "Si"), edgeStep("PROC-REP-070", "PROC-REP-050")])
    );
    assert.ok(activeFeatureIds.includes("FEAT-REP-002"), "expected FEAT-REP-002 active");
    assert.ok(activeFeatureIds.includes("FEAT-REP-007"), "expected FEAT-REP-007 active");
  });

  // F) Traversing PROC-REP-280 activates FEAT-REP-007 and FEAT-REP-008 (both ALWAYS).
  check("F) touching PROC-REP-280 activates FEAT-REP-007 + FEAT-REP-008", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(
      featuresModel,
      makeScenario([edgeStep("PROC-REP-265", "PROC-REP-280", "Si"), edgeStep("PROC-REP-280", "PROC-REP-270")])
    );
    assert.ok(activeFeatureIds.includes("FEAT-REP-007"), "expected FEAT-REP-007 active");
    assert.ok(activeFeatureIds.includes("FEAT-REP-008"), "expected FEAT-REP-008 active");
  });

  // Extra: a FUNCTIONAL_ACTION activates its named Feature even with zero PROCESS_EDGE steps touching it.
  check("G) FUNCTIONAL_ACTION activates its named Feature", () => {
    const { activeFeatureIds } = deriveScenarioFeatures(
      featuresModel,
      makeScenario([{ kind: "FUNCTIONAL_ACTION", feature: "FEAT-REP-007", name: "Registrar pago final" }])
    );
    assert.deepEqual(activeFeatureIds, ["FEAT-REP-007"]);
  });

  // H) Shared-node/binding cardinality: derived from the data, never a
  // hardcoded "11" - expectedBindings = SUM(owners per shared node),
  // actualBindings = SUM(bindings per shared node), and they must match,
  // row by row and in total. This is what would have caught a real bug
  // (e.g. a missing or extra binding) rather than a report-writing typo.
  check("H) shared-node/binding cardinality (5 nodes, owners == bindings everywhere)", () => {
    const sharedNodes = findSharedNodes(featuresModel);
    assert.equal(sharedNodes.size, 5, `expected 5 shared nodes, found ${sharedNodes.size}`);

    const rows = summarizeSharedNodeBindings(featuresModel);
    assert.equal(rows.length, sharedNodes.size, "summary row count must match shared node count");

    console.log("");
    console.log("     node          | owners           | owner_count | bindings         | binding_count");
    let expectedBindings = 0;
    let actualBindings = 0;
    for (const row of rows) {
      console.log(
        `     ${row.node} | ${row.owners.join(",").padEnd(16)} | ${String(row.ownerCount).padEnd(11)} | ` +
          `${row.bindings.join(",").padEnd(16)} | ${row.bindingCount}`
      );
      expectedBindings += row.ownerCount;
      actualBindings += row.bindingCount;
      assert.equal(row.bindingCount, row.ownerCount, `${row.node}: binding_count must equal owner_count`);
      assert.deepEqual(row.bindings, row.owners, `${row.node}: bindings must be exactly the owners, no more/less`);
    }
    console.log(`     TOTAL owner relations = ${expectedBindings}`);
    console.log(`     TOTAL bindings        = ${actualBindings}`);
    console.log("    ");

    assert.equal(actualBindings, expectedBindings, "TOTAL bindings must equal TOTAL owner relations");
  });

  console.log("");
  if (failures > 0) {
    console.error(`FAILED: ${failures} test(s) failed.`);
    process.exit(1);
  }
  console.log("OK: all deriveScenarioFeatures() tests passed.");
}

main();
