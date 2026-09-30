/**
 * Feature <-> process_node <-> Scenario mapping, shared by
 * validate-references.ts, validate-scenarios.ts and
 * generate-process-viewer.ts so the semantics below live in exactly one
 * place - the future Coverage Analyzer will need the same
 * touched/active distinction and should import from here too, not
 * reimplement it.
 *
 * A process_node shared by more than one Feature (N:M by design) can mean
 * two different things, and this module is what tells them apart:
 *
 * - ALWAYS: every Feature that declares the node with mode ALWAYS runs
 *   its behavior every time the node is reached, regardless of how.
 * - CONTEXTUAL: the node is a shared mechanism, and which Feature is
 *   functionally involved depends on which incoming edge led to it
 *   (identified by from + condition + to, the same edge identity used
 *   throughout this repo - see scenario-model.ts). A Scenario activates a
 *   CONTEXTUAL Feature only if it actually contains a matching edge.
 *
 * Three distinct concepts (section 6 of the request that introduced this
 * module - deliberately not called "coverage" yet):
 * - touched_features: raw intersection between a Scenario's visited nodes
 *   and Feature.process_nodes[]. Diagnostic only - can contain semantic
 *   false positives for CONTEXTUAL nodes reached via the "wrong" edge.
 * - active_features: touched_features refined by ALWAYS/CONTEXTUAL
 *   bindings plus FUNCTIONAL_ACTION.feature - the Features genuinely
 *   functionally involved in a Scenario.
 * - covered_features: NOT implemented here. Reserved for a future
 *   Coverage Analyzer (aggregating across many Scenarios) - never conflate
 *   it with "a Scenario happened to pass through this Feature once".
 */
import { edgeKey, type ProcessModel } from "./process-model";
import type { FeatureModel, SharedNodeBinding } from "./feature-model";
import { isFunctionalActionStep, isProcessEdgeStep, type Scenario } from "./scenario-model";

/**
 * Reverse index: process_node id -> Set of Feature ids that declare it in
 * their own process_nodes[]. Always Map<string, Set<string>>, never
 * Map<string, string>: a node legitimately belongs to N Features.
 */
export function buildNodeFeatureIndex(featuresModel: FeatureModel): Map<string, Set<string>> {
  const index = new Map<string, Set<string>>();
  for (const feature of featuresModel.features) {
    for (const nodeId of feature.process_nodes) {
      const owners = index.get(nodeId) ?? new Set<string>();
      owners.add(feature.id);
      index.set(nodeId, owners);
    }
  }
  return index;
}

/** A process_node genuinely shared: declared by more than one Feature. Nodes owned by exactly one Feature need no binding. */
export function findSharedNodes(featuresModel: FeatureModel): Map<string, Set<string>> {
  const shared = new Map<string, Set<string>>();
  for (const [nodeId, owners] of buildNodeFeatureIndex(featuresModel)) {
    if (owners.size > 1) shared.set(nodeId, owners);
  }
  return shared;
}

/**
 * Validates shared_node_bindings structurally+referentially against the
 * Business Process and every Feature's own declarations, and enforces
 * completeness: every Feature that owns a genuinely shared node MUST
 * declare exactly one binding for it (an ERROR, not a warning - the
 * point is to force a new shared node to have its semantics explained
 * instead of silently defaulting to some guess). This is naturally safe
 * for a Features file with zero shared nodes (e.g. V1.2 today): the
 * completeness loop below simply never fires, so V1.2 never needs to
 * adopt this field to keep validating.
 *
 * Returns error strings; never throws, never mutates either model.
 */
export function validateSharedNodeBindings(processModel: ProcessModel, featuresModel: FeatureModel): string[] {
  const errors: string[] = [];
  const nodeIds = new Set(processModel.nodes.map((node) => node.id));
  const processEdgeKeys = new Set(processModel.edges.map((edge) => edgeKey(edge.from, edge.condition, edge.to)));
  const sharedNodes = findSharedNodes(featuresModel);
  const featuresById = new Map(featuresModel.features.map((feature) => [feature.id, feature]));

  for (const feature of featuresModel.features) {
    const bindings = feature.shared_node_bindings ?? [];
    const seenNodes = new Set<string>();

    for (const binding of bindings) {
      if (seenNodes.has(binding.node)) {
        errors.push(`[shared_node_bindings] ${feature.id}: binding duplicado para el node "${binding.node}"`);
      }
      seenNodes.add(binding.node);

      if (!nodeIds.has(binding.node)) {
        errors.push(`[shared_node_bindings] ${feature.id}: node inexistente "${binding.node}"`);
        continue;
      }
      if (!feature.process_nodes.includes(binding.node)) {
        errors.push(
          `[shared_node_bindings] ${feature.id}: declara un binding para "${binding.node}" pero ese node no ` +
            `esta en su process_nodes`
        );
      }
      const owners = sharedNodes.get(binding.node);
      if (!owners || owners.size < 2) {
        errors.push(
          `[shared_node_bindings] ${feature.id}: "${binding.node}" no esta compartido por mas de una Feature, ` +
            `no necesita shared_node_binding`
        );
      }

      const mode: string = binding.mode;
      if (mode === "ALWAYS") {
        if (binding.when) {
          errors.push(`[shared_node_bindings] ${feature.id}: "${binding.node}" es ALWAYS y no debe declarar "when"`);
        }
      } else if (mode === "CONTEXTUAL") {
        const incomingEdges = binding.when?.incoming_edges ?? [];
        if (incomingEdges.length === 0) {
          errors.push(
            `[shared_node_bindings] ${feature.id}: "${binding.node}" es CONTEXTUAL y no declara ningun ` +
              `incoming_edge`
          );
        }
        for (const ref of incomingEdges) {
          if (ref.to !== binding.node) {
            errors.push(
              `[shared_node_bindings] ${feature.id}: "${binding.node}" incoming_edge.to ("${ref.to}") debe ` +
                `coincidir con el node del binding`
            );
          }
          if (!processEdgeKeys.has(edgeKey(ref.from, ref.condition, ref.to))) {
            errors.push(
              `[shared_node_bindings] ${feature.id}: "${binding.node}" incoming_edge ${ref.from} -> ${ref.to}` +
                (ref.condition ? ` (condition "${ref.condition}")` : "") +
                " no existe exactamente en el Business Process"
            );
          }
        }
      } else {
        errors.push(`[shared_node_bindings] ${feature.id}: "${binding.node}" mode invalido "${mode}"`);
      }
    }
  }

  for (const [nodeId, owners] of sharedNodes) {
    for (const featureId of owners) {
      const feature = featuresById.get(featureId);
      const hasBinding = (feature?.shared_node_bindings ?? []).some((binding) => binding.node === nodeId);
      if (!hasBinding) {
        const otherOwners = [...owners].filter((id) => id !== featureId);
        errors.push(
          `[shared_node_bindings] ${featureId}: falta shared_node_binding para el node compartido "${nodeId}" ` +
            `(compartido tambien con ${otherOwners.join(", ")})`
        );
      }
    }
  }

  return errors;
}

export interface SharedNodeBindingSummaryRow {
  node: string;
  owners: string[];
  ownerCount: number;
  bindings: string[];
  bindingCount: number;
}

/**
 * One row per shared node, for reporting/testing cardinality (never
 * hardcode an expected total like "11" - always derive it by summing
 * ownerCount, exactly as this function does): `owners` is every Feature
 * that declares the node in process_nodes[]; `bindings` is the subset of
 * those owners that also declare a shared_node_binding for it. A
 * complete, bug-free model has owners === bindings (same ids, same
 * count) for every row - that equality, summed across rows, is what
 * validateSharedNodeBindings()'s completeness check enforces as errors.
 */
export function summarizeSharedNodeBindings(featuresModel: FeatureModel): SharedNodeBindingSummaryRow[] {
  const sharedNodes = findSharedNodes(featuresModel);
  const featuresById = new Map(featuresModel.features.map((feature) => [feature.id, feature]));

  const rows: SharedNodeBindingSummaryRow[] = [];
  for (const [node, owners] of sharedNodes) {
    const ownerIds = [...owners].sort();
    const bindingIds = ownerIds.filter((featureId) =>
      (featuresById.get(featureId)?.shared_node_bindings ?? []).some((binding) => binding.node === node)
    );
    rows.push({ node, owners: ownerIds, ownerCount: ownerIds.length, bindings: bindingIds, bindingCount: bindingIds.length });
  }
  return rows.sort((a, b) => a.node.localeCompare(b.node));
}

export interface ScenarioFeatureDerivation {
  /** Raw intersection between Scenario nodes and Feature.process_nodes[] - diagnostic only, may over-include CONTEXTUAL false positives. */
  touchedFeatureIds: string[];
  /** touchedFeatureIds refined by ALWAYS/CONTEXTUAL bindings plus FUNCTIONAL_ACTION.feature - the Features genuinely involved. */
  activeFeatureIds: string[];
  /**
   * WHY each active Feature is active: one entry per (node or action) that
   * activated it. A Feature is active when PART of its behavior takes part
   * in the Scenario - it does NOT mean every node/rule of the Feature runs
   * (e.g. FEAT-REP-007 is active in both Happy Paths, with different
   * behavior). Reasons make that explicit instead of implying a single cause.
   */
  activationReasons: Record<string, string[]>;
}

/**
 * Derives touched_features and active_features for one Scenario (section
 * 7). A Feature becomes active when:
 *   A) it owns an EXCLUSIVE node (not shared) that the Scenario visits;
 *   B) it owns a SHARED node with mode ALWAYS that the Scenario visits;
 *   C) it owns a SHARED node with mode CONTEXTUAL, and the Scenario
 *      contains at least one PROCESS_EDGE step matching one of that
 *      binding's when.incoming_edges (by from + condition + to);
 *   D) a FUNCTIONAL_ACTION step names it explicitly.
 *
 * A shared node with no binding for a given Feature never activates that
 * Feature here (validateSharedNodeBindings() is what reports that as a
 * modeling error elsewhere - this function stays conservative instead of
 * guessing).
 *
 * Takes only Features + Scenario: unlike validateSharedNodeBindings(),
 * this derivation never needs to consult the Business Process itself
 * (edge existence is already guaranteed by validate-scenarios.ts by the
 * time this runs).
 */
export function deriveScenarioFeatures(
  featuresModel: FeatureModel,
  scenario: Scenario
): ScenarioFeatureDerivation {
  const steps = scenario.steps ?? []; // a future Variant may declare no steps
  const touchedNodes = new Set<string>();
  for (const step of steps) {
    if (isProcessEdgeStep(step)) {
      touchedNodes.add(step.from);
      touchedNodes.add(step.to);
    }
  }

  const nodeFeatureIndex = buildNodeFeatureIndex(featuresModel);
  const bindingByFeatureAndNode = new Map<string, SharedNodeBinding>();
  for (const feature of featuresModel.features) {
    for (const binding of feature.shared_node_bindings ?? []) {
      bindingByFeatureAndNode.set(`${feature.id}::${binding.node}`, binding);
    }
  }

  const touchedFeatureIds = new Set<string>();
  const activeFeatureIds = new Set<string>();
  const reasons = new Map<string, string[]>();
  const activate = (featureId: string, reason: string): void => {
    activeFeatureIds.add(featureId);
    const list = reasons.get(featureId) ?? [];
    if (!list.includes(reason)) list.push(reason);
    reasons.set(featureId, list);
  };

  for (const feature of featuresModel.features) {
    for (const nodeId of feature.process_nodes) {
      if (!touchedNodes.has(nodeId)) continue;
      touchedFeatureIds.add(feature.id);

      const owners = nodeFeatureIndex.get(nodeId) ?? new Set<string>();
      if (owners.size <= 1) {
        activate(feature.id, `nodo propio ${nodeId}`); // (A) exclusive node
        continue;
      }

      const binding = bindingByFeatureAndNode.get(`${feature.id}::${nodeId}`);
      if (!binding) continue; // missing binding: reported by validateSharedNodeBindings, not guessed here

      if (binding.mode === "ALWAYS") {
        activate(feature.id, `nodo compartido ${nodeId} (ALWAYS)`); // (B)
      } else {
        const satisfied = (binding.when?.incoming_edges ?? []).some((ref) =>
          steps.some(
            (step) =>
              isProcessEdgeStep(step) &&
              step.from === ref.from &&
              step.to === ref.to &&
              (step.condition ?? "") === (ref.condition ?? "")
          )
        );
        if (satisfied) activate(feature.id, `nodo compartido ${nodeId} (CONTEXTUAL)`); // (C)
      }
    }
  }

  for (const step of steps) {
    if (isFunctionalActionStep(step)) {
      touchedFeatureIds.add(step.feature);
      activate(step.feature, `accion funcional "${step.name}"`); // (D)
    }
  }

  return {
    touchedFeatureIds: [...touchedFeatureIds].sort(),
    activeFeatureIds: [...activeFeatureIds].sort(),
    activationReasons: Object.fromEntries([...reasons.entries()].sort(([a], [b]) => a.localeCompare(b))),
  };
}
