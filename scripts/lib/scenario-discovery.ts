/**
 * Structural discovery of alternative paths over the Process Graph.
 *
 * Compares the Process Graph against each Happy Path and reports where the
 * graph offers a transition other than the one the Happy Path took. Each
 * such alternative edge starts a bounded BFS that stops at the first
 * structurally significant outcome (see TerminationType).
 *
 * What this module IS: deterministic topology analysis. What it is NOT:
 * business interpretation. It never decides whether a candidate is a
 * VARIANT, an EXCEPTION or an EDGE_CASE, never names or ranks one, and never
 * looks at node names/descriptions - only at ids, edges and conditions. A
 * "Scenario Candidate" is NOT an approved Scenario.
 *
 * Everything here is a pure function over ProcessModel + Scenario[] (no I/O),
 * so it is testable with synthetic graphs; the CLI lives in
 * scripts/discover-scenario-candidates.ts.
 *
 * Decisions worth knowing:
 * - An edge is identified by from + condition + to (shared `edgeKey`), never
 *   by from/to alone.
 * - Alternatives are computed PER STEP: at step i the baseline edge is the
 *   one the Happy Path took at that step. An edge the Happy Path takes at a
 *   different step (e.g. the 265 -> 266 revalidation loop) is still an
 *   alternative here.
 * - END wins over REJOIN_FORWARD: the end node is on every Happy Path, so
 *   without this precedence a branch that finishes the process on its own
 *   would always be reported as a rejoin and END could never appear.
 * - No combinatorial explosion, by construction: every node is expanded at
 *   most once per deviation (`visited`), so a deviation yields at most one
 *   terminal per edge of the graph, and paths that reconverge on a node
 *   already explored by another branch are pruned (counted, not emitted).
 *   Loops are never unrolled: revisiting a node of the current path is a
 *   CYCLE; returning to the Happy Path is REJOIN_FORWARD/LOOP_TO_BASELINE.
 *
 * Known limitations (documented on purpose, see docs/discovery/README.md):
 * - Only alternatives that leave a node ON a Happy Path are found. Capabilities
 *   that are not sequential edges of the graph (transversal cancellation,
 *   advance payment, actions available from many states) are a future
 *   "Pass 2" and are invisible here.
 * - Cycle detection is BFS + per-path revisit, not Tarjan/SCC; SCC can be
 *   added later if richer loop analysis is needed.
 * - FUNCTIONAL_ACTION steps are ignored (they have no edge).
 */
import { edgeKey, type ProcessEdge, type ProcessModel } from "./process-model";
import { isProcessEdgeStep, type Scenario } from "./scenario-model";

/** Safety bound on the number of edges of one explored deviation. Single source of the default. */
export const DEFAULT_MAX_DEPTH = 30;

export interface DiscoveryConfig {
  maxDepth: number;
}

export const DEFAULT_DISCOVERY_CONFIG: DiscoveryConfig = { maxDepth: DEFAULT_MAX_DEPTH };

export const TERMINATION_TYPES = [
  "REJOIN_FORWARD",
  "LOOP_TO_BASELINE",
  "END",
  "CYCLE",
  "MAX_DEPTH",
  "DEAD_END"
] as const;

/**
 * How an explored deviation ended:
 * - REJOIN_FORWARD: reached a Happy Path node located AFTER the divergence point.
 * - LOOP_TO_BASELINE: reached a Happy Path node located BEFORE or AT the divergence point.
 * - END: reached an `end` node.
 * - CYCLE: revisited a node of its own path without touching the Happy Path first.
 * - MAX_DEPTH: hit the configured depth bound (node = last node reached).
 * - DEAD_END: reached a non-end node with no outgoing edges (safety net; the validated graph has none).
 */
export type TerminationType = (typeof TERMINATION_TYPES)[number];

export interface Termination {
  type: TerminationType;
  node: string;
}

/** A process edge as written in output (condition omitted when the edge has none). */
export interface EdgeRef {
  from: string;
  to: string;
  condition?: string;
}

export interface CandidateOccurrence {
  happy_path: string;
  /** 0-based index among the Happy Path's PROCESS_EDGE steps where the divergence happens. */
  edge_step_index: number;
}

export interface ScenarioCandidate {
  id: string;
  applies_to: string[];
  occurrences: CandidateOccurrence[];
  divergence: { node: string };
  baseline_edge: EdgeRef;
  alternative_edge: EdgeRef;
  explored_path: EdgeRef[];
  termination: Termination;
}

export interface GraphIndex {
  outgoingByNode: Map<string, ProcessEdge[]>;
  nodeTypeById: Map<string, string>;
}

export interface HappyPathBaseline {
  id: string;
  /** The PROCESS_EDGE steps in order, as EdgeRef. */
  edges: EdgeRef[];
  /** Node -> every position it occupies (a node can be visited more than once, e.g. a revalidation loop). */
  positions: Map<string, number[]>;
}

export interface Divergence {
  happyPathId: string;
  stepIndex: number;
  baselineEdge: EdgeRef;
  alternativeEdge: EdgeRef;
}

/** A terminal outcome of one exploration, before deduplication and id assignment. */
export interface RawCandidate {
  happyPathId: string;
  stepIndex: number;
  baselineEdge: EdgeRef;
  alternativeEdge: EdgeRef;
  exploredPath: EdgeRef[];
  termination: Termination;
}

export interface ExplorationResult {
  candidates: RawCandidate[];
  /** Branches dropped because they reconverged on a node already explored by another branch of the same deviation. */
  prunedReconvergences: number;
}

export interface HappyPathStats {
  happyPathId: string;
  /** Steps with at least one alternative outgoing edge. */
  divergencePoints: number;
  /** Alternative outgoing edges found (each starts one exploration). */
  divergences: number;
  candidatesBeforeDedup: number;
  prunedReconvergences: number;
}

export interface DiscoveryResult {
  candidates: ScenarioCandidate[];
  perHappyPath: HappyPathStats[];
  candidatesBeforeDedup: number;
  terminationCounts: Record<TerminationType, number>;
  config: DiscoveryConfig;
}

function toEdgeRef(edge: ProcessEdge): EdgeRef {
  const ref: EdgeRef = { from: edge.from, to: edge.to };
  if (edge.condition !== undefined) ref.condition = edge.condition;
  return ref;
}

function refKey(edge: EdgeRef): string {
  return edgeKey(edge.from, edge.condition, edge.to);
}

/** Builds the graph indexes once, so no lookup ever scans all edges. Outgoing edges keep the process file order. */
export function buildGraphIndex(processModel: ProcessModel): GraphIndex {
  const outgoingByNode = new Map<string, ProcessEdge[]>();
  for (const edge of processModel.edges) {
    const list = outgoingByNode.get(edge.from) ?? [];
    list.push(edge);
    outgoingByNode.set(edge.from, list);
  }
  const nodeTypeById = new Map(processModel.nodes.map((node) => [node.id, node.type as string]));
  return { outgoingByNode, nodeTypeById };
}

/** The ordered PROCESS_EDGE steps of a Happy Path plus the position(s) of every node on it. */
export function getHappyPathBaseline(scenario: Scenario): HappyPathBaseline {
  const edges = (scenario.steps ?? []).filter(isProcessEdgeStep).map(toEdgeRef);
  const positions = new Map<string, number[]>();
  const addPosition = (node: string, position: number): void => {
    const list = positions.get(node) ?? [];
    list.push(position);
    positions.set(node, list);
  };
  edges.forEach((edge, index) => addPosition(edge.from, index));
  if (edges.length > 0) addPosition(edges[edges.length - 1].to, edges.length);
  return { id: scenario.id, edges, positions };
}

/** For every step, each outgoing edge of `from` that is not the edge the Happy Path took at that step. */
export function findDivergences(baseline: HappyPathBaseline, index: GraphIndex): Divergence[] {
  const divergences: Divergence[] = [];
  baseline.edges.forEach((baselineEdge, stepIndex) => {
    const baselineKey = refKey(baselineEdge);
    for (const outgoing of index.outgoingByNode.get(baselineEdge.from) ?? []) {
      if (edgeKey(outgoing.from, outgoing.condition, outgoing.to) === baselineKey) continue;
      divergences.push({ happyPathId: baseline.id, stepIndex, baselineEdge, alternativeEdge: toEdgeRef(outgoing) });
    }
  });
  return divergences;
}

function classifyHappyPathNode(node: string, positions: number[], divergenceStep: number): Termination {
  const isForward = positions.some((position) => position > divergenceStep);
  return { type: isForward ? "REJOIN_FORWARD" : "LOOP_TO_BASELINE", node };
}

/**
 * BFS from one alternative edge, stopping every branch at its first
 * structural outcome. Check order on arriving at a node: end -> Happy Path
 * node (rejoin/loop) -> revisit of this path (cycle) -> already explored by
 * another branch (pruned) -> depth bound -> expand.
 */
export function exploreDeviationBfs(
  divergence: Divergence,
  baseline: HappyPathBaseline,
  index: GraphIndex,
  config: DiscoveryConfig = DEFAULT_DISCOVERY_CONFIG
): ExplorationResult {
  const candidates: RawCandidate[] = [];
  let prunedReconvergences = 0;
  const visited = new Set<string>();
  const queue: EdgeRef[][] = [[divergence.alternativeEdge]];

  const emit = (path: EdgeRef[], termination: Termination): void => {
    candidates.push({
      happyPathId: divergence.happyPathId,
      stepIndex: divergence.stepIndex,
      baselineEdge: divergence.baselineEdge,
      alternativeEdge: divergence.alternativeEdge,
      exploredPath: path,
      termination
    });
  };

  for (let head = 0; head < queue.length; head++) {
    const path = queue[head];
    const node = path[path.length - 1].to;
    const happyPathPositions = baseline.positions.get(node);

    if (index.nodeTypeById.get(node) === "end") {
      emit(path, { type: "END", node });
    } else if (happyPathPositions !== undefined) {
      emit(path, classifyHappyPathNode(node, happyPathPositions, divergence.stepIndex));
    } else if (path.some((edge) => edge.from === node)) {
      emit(path, { type: "CYCLE", node });
    } else if (visited.has(node)) {
      prunedReconvergences++;
    } else {
      visited.add(node);
      const outgoing = index.outgoingByNode.get(node) ?? [];
      if (path.length >= config.maxDepth) {
        emit(path, { type: "MAX_DEPTH", node });
      } else if (outgoing.length === 0) {
        emit(path, { type: "DEAD_END", node });
      } else {
        for (const edge of outgoing) queue.push([...path, toEdgeRef(edge)]);
      }
    }
  }
  return { candidates, prunedReconvergences };
}

/**
 * Deterministic structural signature. Deliberately WITHOUT the Happy Path id
 * so the same deviation found on several Happy Paths deduplicates into one
 * candidate. It includes the baseline edge (the same alternative taken
 * against a different baseline is a different deviation), the alternative
 * edge, the whole explored path and the termination.
 */
export function buildCandidateSignature(candidate: RawCandidate): string {
  return JSON.stringify([
    refKey(candidate.baselineEdge),
    refKey(candidate.alternativeEdge),
    candidate.exploredPath.map(refKey),
    candidate.termination.type,
    candidate.termination.node
  ]);
}

interface UnidentifiedCandidate extends Omit<ScenarioCandidate, "id"> {
  signature: string;
}

function compareText(a: string, b: string): number {
  return a < b ? -1 : a > b ? 1 : 0;
}

/** Merges structurally identical candidates, accumulating applies_to and occurrences. */
export function deduplicateCandidates(rawCandidates: RawCandidate[]): UnidentifiedCandidate[] {
  const bySignature = new Map<string, UnidentifiedCandidate>();
  for (const raw of rawCandidates) {
    const signature = buildCandidateSignature(raw);
    const occurrence: CandidateOccurrence = { happy_path: raw.happyPathId, edge_step_index: raw.stepIndex };
    const existing = bySignature.get(signature);
    if (existing === undefined) {
      bySignature.set(signature, {
        signature,
        applies_to: [raw.happyPathId],
        occurrences: [occurrence],
        divergence: { node: raw.alternativeEdge.from },
        baseline_edge: raw.baselineEdge,
        alternative_edge: raw.alternativeEdge,
        explored_path: raw.exploredPath,
        termination: raw.termination
      });
    } else {
      if (!existing.applies_to.includes(raw.happyPathId)) existing.applies_to.push(raw.happyPathId);
      existing.occurrences.push(occurrence);
    }
  }
  const merged = [...bySignature.values()];
  for (const candidate of merged) {
    candidate.applies_to.sort(compareText);
    candidate.occurrences.sort(
      (a, b) => compareText(a.happy_path, b.happy_path) || a.edge_step_index - b.edge_step_index
    );
  }
  return merged;
}

/** "PROC-REP" -> "CAND-REP" (the id prefix follows the process id). */
export function candidateIdPrefix(processId: string): string {
  return processId.startsWith("PROC-") ? `CAND-${processId.slice("PROC-".length)}` : `CAND-${processId}`;
}

/**
 * Sorts candidates in a total, input-order-independent way (divergence node,
 * alternative edge, baseline edge, termination, signature as tie-break) and
 * numbers them, so two runs on the same model produce the same ids.
 */
export function assignStableCandidateIds(candidates: UnidentifiedCandidate[], idPrefix: string): ScenarioCandidate[] {
  const sorted = [...candidates].sort(
    (a, b) =>
      compareText(a.divergence.node, b.divergence.node) ||
      compareText(refKey(a.alternative_edge), refKey(b.alternative_edge)) ||
      compareText(refKey(a.baseline_edge), refKey(b.baseline_edge)) ||
      compareText(a.termination.type, b.termination.type) ||
      compareText(a.termination.node, b.termination.node) ||
      compareText(a.signature, b.signature)
  );
  const width = Math.max(3, String(sorted.length).length);
  return sorted.map((candidate, position) => {
    const { signature: _signature, ...rest } = candidate;
    return { id: `${idPrefix}-${String(position + 1).padStart(width, "0")}`, ...rest };
  });
}

/** Orchestrator: every E2E Happy Path against the graph -> deduplicated, identified candidates plus statistics. */
export function discoverScenarioCandidates(
  processModel: ProcessModel,
  scenarios: Scenario[],
  config: DiscoveryConfig = DEFAULT_DISCOVERY_CONFIG
): DiscoveryResult {
  const index = buildGraphIndex(processModel);
  const happyPaths = scenarios.filter((scenario) => scenario.type === "HAPPY_PATH" && scenario.scope === "E2E");

  const raw: RawCandidate[] = [];
  const perHappyPath: HappyPathStats[] = [];
  for (const happyPath of happyPaths) {
    const baseline = getHappyPathBaseline(happyPath);
    const divergences = findDivergences(baseline, index);
    let prunedReconvergences = 0;
    let candidatesBeforeDedup = 0;
    for (const divergence of divergences) {
      const result = exploreDeviationBfs(divergence, baseline, index, config);
      raw.push(...result.candidates);
      candidatesBeforeDedup += result.candidates.length;
      prunedReconvergences += result.prunedReconvergences;
    }
    perHappyPath.push({
      happyPathId: happyPath.id,
      divergencePoints: new Set(divergences.map((divergence) => divergence.stepIndex)).size,
      divergences: divergences.length,
      candidatesBeforeDedup,
      prunedReconvergences
    });
  }

  const candidates = assignStableCandidateIds(deduplicateCandidates(raw), candidateIdPrefix(processModel.process.id));
  const terminationCounts = Object.fromEntries(TERMINATION_TYPES.map((type) => [type, 0])) as Record<
    TerminationType,
    number
  >;
  for (const candidate of candidates) terminationCounts[candidate.termination.type]++;

  return { candidates, perHappyPath, candidatesBeforeDedup: raw.length, terminationCounts, config };
}
