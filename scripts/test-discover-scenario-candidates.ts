/**
 * Dependency-free tests for the structural scenario-candidate discovery
 * (scripts/lib/scenario-discovery.ts + scripts/discover-scenario-candidates.ts).
 *
 * Part 1 uses tiny synthetic graphs so each algorithmic rule is proven in
 * isolation (alternatives, edge identity, every termination type, dedup,
 * stable ids). Part 2 asserts facts about the REAL PROC-REP V1.3 graph and
 * Happy Paths, and that the generator never modifies the source scenarios.
 *
 * Run with `tsx scripts/test-discover-scenario-candidates.ts`. Same style as
 * the other test scripts: node:assert/strict, no framework.
 */
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { edgeKey, loadYaml, type NodeType, type ProcessModel } from "./lib/process-model";
import type { Scenario, ScenarioModel } from "./lib/scenario-model";
import {
  DEFAULT_MAX_DEPTH,
  buildCandidateSignature,
  buildGraphIndex,
  discoverScenarioCandidates,
  exploreDeviationBfs,
  findDivergences,
  getHappyPathBaseline,
  type DiscoveryResult,
  type RawCandidate,
  type ScenarioCandidate,
  type TerminationType
} from "./lib/scenario-discovery";

const PROCESS_FILE = "business/processes/repair-management-v1.3.yaml";
const SCENARIOS_FILE = "business/scenarios/repair-management-scenarios-v1.3.yaml";
const CLI_FILE = "scripts/discover-scenario-candidates.ts";

const realProcess = loadYaml<ProcessModel>(PROCESS_FILE);
const realScenarios = loadYaml<ScenarioModel>(SCENARIOS_FILE).scenarios;
const realResult = discoverScenarioCandidates(realProcess, realScenarios);

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

// ---------------------------------------------------------------- fixtures

type EdgeSpec = [from: string, to: string, condition?: string];

function graph(edges: EdgeSpec[], endIds: string[] = ["E"], extraNodes: string[] = []): ProcessModel {
  const ids = new Set<string>(extraNodes);
  for (const [from, to] of edges) {
    ids.add(from);
    ids.add(to);
  }
  for (const end of endIds) ids.add(end);
  return {
    process: { id: "PROC-TST", name: "Test", version: "0" },
    nodes: [...ids].map((id) => ({ id, type: (endIds.includes(id) ? "end" : "activity") as NodeType, name: id })),
    // Fixtures share edges between Happy Paths: keep each edge (by identity) once.
    edges: edges
      .filter(([from, to, condition], position) => edges.findIndex(([f, t, c]) => edgeKey(f, c, t) === edgeKey(from, condition, to)) === position)
      .map(([from, to, condition]) => (condition === undefined ? { from, to } : { from, to, condition }))
  };
}

function happyPath(id: string, edges: EdgeSpec[]): Scenario {
  return {
    id,
    name: id,
    type: "HAPPY_PATH",
    scope: "E2E",
    status: "draft",
    source_process: { id: "PROC-TST", version: "0" },
    description: id,
    facts: [],
    expected: [],
    steps: edges.map(([from, to, condition]) =>
      condition === undefined
        ? { kind: "PROCESS_EDGE" as const, from, to }
        : { kind: "PROCESS_EDGE" as const, from, to, condition }
    )
  };
}

const HP_EDGES: EdgeSpec[] = [
  ["A", "B"],
  ["B", "C"],
  ["C", "D"],
  ["D", "E"]
];

function discover(extra: EdgeSpec[], endIds?: string[], config?: { maxDepth: number }, hp: EdgeSpec[] = HP_EDGES): DiscoveryResult {
  return discoverScenarioCandidates(graph([...hp, ...extra], endIds), [happyPath("HP-1", hp)], config);
}

function pathKeys(candidate: ScenarioCandidate): string[] {
  return candidate.explored_path.map((edge) => `${edge.from}>${edge.to}`);
}

console.log("\nAlgoritmo (grafos sinteticos)\n");

check("1) detecta un outgoing edge alternativo", () => {
  const result = discover([["C", "X"], ["X", "D"]]);
  assert.equal(result.candidates.length, 1);
  assert.deepEqual(result.candidates[0].alternative_edge, { from: "C", to: "X" });
  assert.equal(result.candidates[0].divergence.node, "C");
});

check("2) no devuelve como alternativo el edge elegido por el HP", () => {
  const model = graph([...HP_EDGES, ["C", "X"], ["X", "D"]]);
  const baseline = getHappyPathBaseline(happyPath("HP-1", HP_EDGES));
  const divergences = findDivergences(baseline, buildGraphIndex(model));
  assert.equal(divergences.length, 1);
  for (const divergence of divergences) {
    assert.notEqual(
      edgeKey(divergence.alternativeEdge.from, divergence.alternativeEdge.condition, divergence.alternativeEdge.to),
      edgeKey(divergence.baselineEdge.from, divergence.baselineEdge.condition, divergence.baselineEdge.to)
    );
  }
  assert.equal(discover([]).candidates.length, 0, "un grafo sin desvios no produce candidatos");
});

check("3) respeta from + condition + to (mismo from/to, distinta condicion)", () => {
  const hp: EdgeSpec[] = [["A", "B", "ok"], ["B", "E"]];
  const result = discover([["A", "B", "ko"], ["A", "B"]], undefined, undefined, hp);
  const conditions = result.candidates.map((candidate) => candidate.alternative_edge.condition ?? "(sin condicion)").sort();
  assert.deepEqual(conditions, ["(sin condicion)", "ko"], "el edge con condicion 'ok' es el baseline; 'ko' y sin condicion son alternativos");
  for (const candidate of result.candidates) assert.deepEqual(candidate.termination, { type: "REJOIN_FORWARD", node: "B" });
});

check("4) detecta REJOIN_FORWARD", () => {
  const [candidate] = discover([["C", "X"], ["X", "Y"], ["Y", "D"]]).candidates;
  assert.deepEqual(candidate.termination, { type: "REJOIN_FORWARD", node: "D" });
  assert.deepEqual(pathKeys(candidate), ["C>X", "X>Y", "Y>D"]);
});

check("5) detecta LOOP_TO_BASELINE (nodo anterior o el mismo punto de divergencia)", () => {
  const [back] = discover([["C", "X"], ["X", "Y"], ["Y", "B"]]).candidates;
  assert.deepEqual(back.termination, { type: "LOOP_TO_BASELINE", node: "B" });
  const [same] = discover([["C", "X"], ["X", "C"]]).candidates;
  assert.deepEqual(same.termination, { type: "LOOP_TO_BASELINE", node: "C" });
});

check("6) detecta END (y END gana sobre REJOIN cuando el nodo end esta en el HP)", () => {
  const otherEnd = discover([["C", "X"], ["X", "F"]], ["E", "F"]);
  assert.deepEqual(otherEnd.candidates[0].termination, { type: "END", node: "F" });
  const hpEnd = discover([["C", "X"], ["X", "E"]]);
  assert.deepEqual(hpEnd.candidates[0].termination, { type: "END", node: "E" });
});

check("7) detecta CYCLE (revisita un nodo de su propio recorrido sin tocar el HP)", () => {
  const [candidate] = discover([["C", "X"], ["X", "Y"], ["Y", "Z"], ["Z", "Y"]]).candidates;
  assert.deepEqual(candidate.termination, { type: "CYCLE", node: "Y" });
  assert.deepEqual(pathKeys(candidate), ["C>X", "X>Y", "Y>Z", "Z>Y"]);
  const [selfLoop] = discover([["C", "X"], ["X", "X"]]).candidates;
  assert.deepEqual(selfLoop.termination, { type: "CYCLE", node: "X" });
});

check("8) respeta MAX_DEPTH (configurable; el default esta centralizado)", () => {
  const chain: EdgeSpec[] = [["C", "N1"], ["N1", "N2"], ["N2", "N3"], ["N3", "N4"], ["N4", "N5"], ["N5", "D"]];
  const [limited] = discover(chain, undefined, { maxDepth: 3 }).candidates;
  assert.deepEqual(limited.termination, { type: "MAX_DEPTH", node: "N3" });
  assert.equal(limited.explored_path.length, 3);
  const [free] = discover(chain).candidates;
  assert.deepEqual(free.termination, { type: "REJOIN_FORWARD", node: "D" });
  assert.equal(DEFAULT_MAX_DEPTH, 30);
});

check("9) no entra en loop infinito (ciclos, self-loops y cadenas largas terminan)", () => {
  const cyclic: EdgeSpec[] = [["C", "X"], ["X", "Y"], ["Y", "X"], ["Y", "Z"], ["Z", "X"], ["Z", "Z"]];
  const result = discover(cyclic);
  assert.ok(result.candidates.length > 0);
  assert.ok(result.candidates.every((candidate) => candidate.explored_path.length <= DEFAULT_MAX_DEPTH));
});

check("bonus) un nodo sin salidas que no es end produce DEAD_END", () => {
  const [candidate] = discover([["C", "X"]]).candidates;
  assert.deepEqual(candidate.termination, { type: "DEAD_END", node: "X" });
});

check("bonus) una desviacion que se ramifica produce un candidato por desenlace, sin combinaciones", () => {
  const result = discover([["C", "X"], ["X", "Y", "a"], ["X", "B", "b"], ["Y", "D"], ["Y", "E", "z"]]);
  const outcomes = result.candidates.map((candidate) => `${candidate.termination.type}@${candidate.termination.node}`).sort();
  assert.deepEqual(outcomes, ["END@E", "LOOP_TO_BASELINE@B", "REJOIN_FORWARD@D"]);
});

check("bonus) ramas que reconvergen en un nodo ya explorado se podan, no se multiplican", () => {
  const model = graph([...HP_EDGES, ["C", "X"], ["X", "P", "1"], ["X", "Q", "2"], ["P", "M"], ["Q", "M"], ["M", "D"]]);
  const baseline = getHappyPathBaseline(happyPath("HP-1", HP_EDGES));
  const index = buildGraphIndex(model);
  const [divergence] = findDivergences(baseline, index);
  const result = exploreDeviationBfs(divergence, baseline, index);
  assert.equal(result.candidates.length, 1);
  assert.equal(result.prunedReconvergences, 1);
});

console.log("\nDeduplicacion, firma e ids\n");

const HP2_EDGES: EdgeSpec[] = [
  ["A", "B"],
  ["B", "C"],
  ["C", "D"],
  ["D", "E"]
];

function discoverTwo(extra: EdgeSpec[], hp2: EdgeSpec[] = HP2_EDGES): DiscoveryResult {
  return discoverScenarioCandidates(graph([...HP_EDGES, ...hp2, ...extra]), [happyPath("HP-1", HP_EDGES), happyPath("HP-2", hp2)]);
}

check("10) deduplica el mismo candidate entre Happy Paths", () => {
  const result = discoverTwo([["C", "X"], ["X", "D"]]);
  assert.equal(result.candidatesBeforeDedup, 2);
  assert.equal(result.candidates.length, 1);
});

check("11) acumula correctamente applies_to y occurrences (ordenados)", () => {
  const result = discoverScenarioCandidates(graph([...HP_EDGES, ["C", "X"], ["X", "D"]]), [
    happyPath("HP-2", HP_EDGES),
    happyPath("HP-1", HP_EDGES)
  ]);
  assert.deepEqual(result.candidates[0].applies_to, ["HP-1", "HP-2"]);
  assert.deepEqual(result.candidates[0].occurrences, [
    { happy_path: "HP-1", edge_step_index: 2 },
    { happy_path: "HP-2", edge_step_index: 2 }
  ]);
});

check("12) no fusiona candidatos estructuralmente diferentes (otro camino, otra terminacion, otro baseline)", () => {
  const viaX = (result: DiscoveryResult): ScenarioCandidate[] =>
    result.candidates.filter((candidate) => candidate.alternative_edge.to === "X");
  // Same alternative C -> X -> M: M is on HP-2 (rejoin) but not on HP-1 (keeps going to the end).
  const differentTermination = viaX(discoverTwo([["C", "X"], ["X", "M"]], [["A", "B"], ["B", "C"], ["C", "M"], ["M", "E"]]));
  assert.deepEqual(
    differentTermination.map((candidate) => [candidate.termination.type, candidate.applies_to]),
    [["END", ["HP-1"]], ["REJOIN_FORWARD", ["HP-2"]]]
  );
  // Same alternative, same path, same termination, but a different baseline edge (C -> D vs C -> Q): different deviations.
  const differentBaseline = viaX(discoverTwo([["C", "X"], ["X", "D"]], [["A", "B"], ["B", "C"], ["C", "Q"], ["Q", "D"], ["D", "E"]]));
  assert.equal(differentBaseline.length, 2);
  assert.notDeepEqual(differentBaseline[0].baseline_edge, differentBaseline[1].baseline_edge);
  // A different explored path with the same endpoints is a different candidate.
  const twoPaths = discover([["C", "X"], ["X", "D"], ["C", "Y"], ["Y", "D"]]);
  assert.equal(twoPaths.candidates.length, 2);
});

check("la firma no incluye el id del Happy Path", () => {
  const raw = (happyPathId: string): RawCandidate => ({
    happyPathId,
    stepIndex: 2,
    baselineEdge: { from: "C", to: "D" },
    alternativeEdge: { from: "C", to: "X" },
    exploredPath: [{ from: "C", to: "X" }, { from: "X", to: "D" }],
    termination: { type: "REJOIN_FORWARD", node: "D" }
  });
  assert.equal(buildCandidateSignature(raw("HP-1")), buildCandidateSignature(raw("HP-2")));
  assert.ok(!buildCandidateSignature(raw("HP-1")).includes("HP-1"));
});

check("13) los ids son estables: no dependen del orden de entrada", () => {
  const extra: EdgeSpec[] = [["C", "X"], ["X", "D"], ["B", "Y"], ["Y", "B"], ["A", "Z"], ["Z", "E"]];
  const forward = discover(extra);
  const reversed = discover([...extra].reverse());
  assert.deepEqual(reversed.candidates, forward.candidates);
  assert.deepEqual(forward.candidates.map((candidate) => candidate.id), ["CAND-TST-001", "CAND-TST-002", "CAND-TST-003"]);
  assert.deepEqual(forward.candidates.map((candidate) => candidate.divergence.node), ["A", "B", "C"], "ordenados por nodo de divergencia");
  const swappedScenarios = discoverScenarioCandidates(graph([...HP_EDGES, ...HP2_EDGES, ...extra]), [happyPath("HP-2", HP2_EDGES), happyPath("HP-1", HP_EDGES)]);
  const normalScenarios = discoverScenarioCandidates(graph([...HP_EDGES, ...HP2_EDGES, ...extra]), [happyPath("HP-1", HP_EDGES), happyPath("HP-2", HP2_EDGES)]);
  assert.deepEqual(swappedScenarios.candidates, normalScenarios.candidates);
});

check("14) mismo input produce mismo output (objeto y YAML renderizado)", () => {
  const first = discoverScenarioCandidates(realProcess, realScenarios);
  const second = discoverScenarioCandidates(realProcess, realScenarios);
  assert.deepEqual(first, second);
  assert.equal(JSON.stringify(first.candidates), JSON.stringify(second.candidates));
});

// ------------------------------------------------------------ real graph

const HAPPY_PATH_IDS = ["HP-REP-001", "HP-REP-002", "HP-REP-003"];

function find(predicate: (candidate: ScenarioCandidate) => boolean): ScenarioCandidate[] {
  return realResult.candidates.filter(predicate);
}

console.log("\nProcess Graph V1.3 real\n");

check("analiza los 3 Happy Paths y cada uno tiene divergencias", () => {
  assert.deepEqual(realResult.perHappyPath.map((stats) => stats.happyPathId), HAPPY_PATH_IDS);
  for (const stats of realResult.perHappyPath) {
    assert.ok(stats.divergences > 0, stats.happyPathId);
    assert.ok(stats.divergencePoints > 0 && stats.divergencePoints <= stats.divergences);
    assert.ok(stats.candidatesBeforeDedup >= stats.divergences - stats.prunedReconvergences);
  }
  assert.ok(realResult.candidates.length > 0);
  assert.ok(realResult.candidates.length <= realResult.candidatesBeforeDedup);
});

check("cada candidato es estructuralmente coherente con el grafo real", () => {
  const processEdgeKeys = new Set(realProcess.edges.map((edge) => edgeKey(edge.from, edge.condition, edge.to)));
  for (const candidate of realResult.candidates) {
    const key = (edge: { from: string; to: string; condition?: string }): string => edgeKey(edge.from, edge.condition, edge.to);
    assert.notEqual(key(candidate.alternative_edge), key(candidate.baseline_edge), candidate.id);
    assert.equal(candidate.alternative_edge.from, candidate.baseline_edge.from, candidate.id);
    assert.equal(candidate.divergence.node, candidate.baseline_edge.from);
    assert.deepEqual(candidate.explored_path[0], candidate.alternative_edge, candidate.id);
    candidate.explored_path.forEach((edge, position) => {
      assert.ok(processEdgeKeys.has(key(edge)), `${candidate.id}: edge inexistente ${key(edge)}`);
      if (position > 0) assert.equal(candidate.explored_path[position - 1].to, edge.from, `${candidate.id}: path discontinuo`);
    });
    assert.ok(candidate.applies_to.length > 0 && candidate.applies_to.every((id) => HAPPY_PATH_IDS.includes(id)));
    assert.equal(candidate.occurrences.length >= candidate.applies_to.length, true);
  }
});

check("PROC-REP-090 'Ninguno trabajable' aplica a los tres HP (LOOP a 080 y REJOIN a 140)", () => {
  const fromNoWorkable = find((c) => c.alternative_edge.from === "PROC-REP-090" && c.alternative_edge.condition === "Ninguno trabajable");
  const kinds = fromNoWorkable.map((c) => `${c.termination.type}@${c.termination.node}`).sort();
  assert.deepEqual(kinds, ["LOOP_TO_BASELINE@PROC-REP-080", "REJOIN_FORWARD@PROC-REP-140"]);
  for (const candidate of fromNoWorkable) assert.deepEqual(candidate.applies_to, HAPPY_PATH_IDS);
});

check("200 -> 210 [Interrumpido] (mismo from/to que Completado) se detecta como alternativo", () => {
  const [candidate] = find((c) => c.alternative_edge.from === "PROC-REP-200");
  assert.equal(candidate.alternative_edge.condition, "Interrumpido");
  assert.equal(candidate.baseline_edge.condition, "Completado");
  assert.deepEqual(candidate.termination, { type: "REJOIN_FORWARD", node: "PROC-REP-210" });
});

check("211 [Todos cancelados] llega directo al fin del proceso (END)", () => {
  const ends = find((c) => c.termination.type === "END");
  assert.equal(ends.length, 1);
  assert.equal(ends[0].alternative_edge.from, "PROC-REP-211");
  assert.equal(ends[0].alternative_edge.condition, "Todos cancelados");
  assert.deepEqual(ends[0].applies_to, HAPPY_PATH_IDS);
});

check("el circuito de revalidacion 265 <-> 266 aparece como LOOP_TO_BASELINE y CYCLE", () => {
  assert.ok(find((c) => c.termination.type === "LOOP_TO_BASELINE" && c.alternative_edge.from === "PROC-REP-265").length > 0);
  const cycles = find((c) => c.termination.type === "CYCLE");
  assert.ok(cycles.length >= 1);
  assert.ok(cycles.every((c) => c.explored_path.length > 1));
});

check("250 se desvia en sentido opuesto en HP-002 vs HP-001/003 y no se fusiona", () => {
  const at250 = find((c) => c.divergence.node === "PROC-REP-250");
  const towards290 = at250.filter((c) => c.alternative_edge.to === "PROC-REP-290");
  const towards260 = at250.filter((c) => c.alternative_edge.to === "PROC-REP-260");
  assert.deepEqual(towards290.map((c) => c.applies_to), [["HP-REP-001", "HP-REP-003"]]);
  assert.ok(towards260.every((c) => c.applies_to.length === 1 && c.applies_to[0] === "HP-REP-002"));
});

check("los desvios del origen (010) reflejan el HP de cada uno", () => {
  const at010 = find((c) => c.divergence.node === "PROC-REP-010");
  assert.equal(at010.length, 6, "3 orígenes alternativos para HP-001 y 3 para HP-002 (HP-003 no pasa por 010)");
  assert.ok(at010.every((c) => !c.applies_to.includes("HP-REP-003")));
});

check("con el default no se llega a MAX_DEPTH en el grafo real", () => {
  assert.equal(realResult.terminationCounts.MAX_DEPTH, 0);
  assert.equal(realResult.terminationCounts.DEAD_END, 0);
});

check("ids consecutivos CAND-REP-001..N y sin campos de interpretacion de negocio", () => {
  assert.deepEqual(
    realResult.candidates.map((c) => c.id),
    realResult.candidates.map((_, position) => `CAND-REP-${String(position + 1).padStart(3, "0")}`)
  );
  const forbidden = ["suggested_type", "business_name", "severity", "name", "type", "classification"];
  for (const candidate of realResult.candidates) {
    for (const field of forbidden) assert.ok(!(field in candidate), `${candidate.id} no debe tener "${field}"`);
  }
  const counted = Object.values(realResult.terminationCounts).reduce((sum, n) => sum + n, 0);
  assert.equal(counted, realResult.candidates.length);
});

check("15) el generador no modifica el YAML fuente de scenarios ni el del proceso; escribe un artefacto marcado como generado", () => {
  const hash = (file: string): string => createHash("sha256").update(readFileSync(file)).digest("hex");
  const before = [hash(SCENARIOS_FILE), hash(PROCESS_FILE)];
  const dir = mkdtempSync(join(tmpdir(), "scenario-candidates-"));
  const output = join(dir, "candidates.yaml");
  try {
    execFileSync(process.execPath, ["--import", "tsx", CLI_FILE, PROCESS_FILE, SCENARIOS_FILE, output], { stdio: "pipe" });
    const text = readFileSync(output, "utf8");
    assert.match(text, /GENERATED FILE - DO NOT EDIT BY HAND/);
    assert.match(text, /NOT A SOURCE OF TRUTH/);
    assert.match(text, /NOT CONFIRMED BUSINESS SCENARIOS/);
    assert.match(text, /status: GENERATED_NOT_SOURCE_OF_TRUTH/);
    assert.ok(!/[&*]a\d+/.test(text), "sin anchors/aliases YAML");
    const again = join(dir, "candidates-2.yaml");
    execFileSync(process.execPath, ["--import", "tsx", CLI_FILE, PROCESS_FILE, SCENARIOS_FILE, again], { stdio: "pipe" });
    assert.equal(readFileSync(again, "utf8"), text, "dos ejecuciones producen el mismo archivo");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
  assert.deepEqual([hash(SCENARIOS_FILE), hash(PROCESS_FILE)], before);
});

check("todos los tipos de terminacion son los documentados", () => {
  const known: TerminationType[] = ["REJOIN_FORWARD", "LOOP_TO_BASELINE", "END", "CYCLE", "MAX_DEPTH", "DEAD_END"];
  assert.deepEqual(Object.keys(realResult.terminationCounts).sort(), [...known].sort());
});

console.log("");
if (failures > 0) {
  console.error(`FAILED: ${failures} test(s) failed.`);
  process.exit(1);
}
console.log("OK: all scenario-discovery tests passed.");
