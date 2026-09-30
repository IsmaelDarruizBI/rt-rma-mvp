/**
 * Shared types for the Scenario YAML model (business/scenarios/*.yaml).
 * Mirrors the shape validated by business/schemas/scenario.schema.json.
 *
 * A Scenario is a LAYER over the Business Process: it never duplicates
 * nodes/edges, it references them. Two kinds of step exist:
 * - PROCESS_EDGE: an actual transition of the Business Process
 *   (from/to/condition, matched 1:1 against process.edges).
 * - FUNCTIONAL_ACTION: a real functional capability that has no
 *   sequential node of its own in the Business Process (e.g. Registrar
 *   Pago, a transversal capability of a Feature) - it never creates a new
 *   Mermaid line, it is shown only in the Scenario's own step list.
 *
 * Only HAPPY_PATH/E2E is implemented and validated end-to-end in this
 * iteration. VARIANT/EXCEPTION/EDGE_CASE and FEATURE/RULE scope are kept
 * in the type/enum so a future iteration can add them without a schema
 * or type change, but their semantics (e.g. Variant fact overrides over
 * a Happy Path baseline) are deliberately not implemented yet.
 *
 * Used by validate-scenarios.ts and generate-process-viewer.ts so the
 * shape of a Scenario is defined in exactly one place. Loading is done
 * via `loadYaml` from ./process-model, reused rather than duplicated.
 */

export type ScenarioType = "HAPPY_PATH" | "VARIANT" | "EXCEPTION" | "EDGE_CASE";
export type ScenarioScope = "E2E" | "FEATURE" | "RULE";

export type FactValue = string | boolean | number;

export interface ScenarioFact {
  key: string;
  label: string;
  value: FactValue;
}

export interface ScenarioSourceProcess {
  id: string;
  version: string;
}

export interface ProcessEdgeStep {
  kind: "PROCESS_EDGE";
  from: string;
  to: string;
  condition?: string;
}

export interface FunctionalActionStep {
  kind: "FUNCTIONAL_ACTION";
  feature: string;
  name: string;
  description?: string;
}

export type ScenarioStep = ProcessEdgeStep | FunctionalActionStep;

export function isProcessEdgeStep(step: ScenarioStep): step is ProcessEdgeStep {
  return step.kind === "PROCESS_EDGE";
}

export function isFunctionalActionStep(step: ScenarioStep): step is FunctionalActionStep {
  return step.kind === "FUNCTIONAL_ACTION";
}

/** A node this Scenario deliberately does NOT traverse, with the reason (documentary; the path itself is always driven by steps[]). */
export interface SkippedNode {
  node: string;
  reason: string;
}

export interface ScenarioEdgeRef {
  from: string;
  to: string;
  condition?: string;
}

/** Where a Variant/Exception/Edge Case originates in the Process Graph. */
export interface ScenarioTrigger {
  node: string;
  edge?: ScenarioEdgeRef;
  condition?: string;
}

/**
 * Relations between non-happy-path scenarios (ids of other scenarios).
 * Only the SHAPE is defined today: how requires/enables/implies/excludes
 * combine at execution time is deliberately not implemented yet.
 */
export interface ScenarioDependencies {
  requires?: string[];
  enables?: string[];
  implies?: string[];
  excludes?: string[];
}

export interface Scenario {
  id: string;
  name: string;
  type: ScenarioType;
  scope: ScenarioScope;
  status: string;
  source_process: ScenarioSourceProcess;
  description: string;
  // The schema only REQUIRES facts/steps/expected for HAPPY_PATH (a future
  // Variant is a deviation, not a full path). They are typed as required
  // here because every scenario that exists today is a HAPPY_PATH; the
  // day a real Variant lands, these three become optional in this type
  // and the consumers (validator/viewer) get a normalization step.
  facts: ScenarioFact[];
  steps: ScenarioStep[];
  expected: ScenarioFact[];
  skipped_nodes?: SkippedNode[];

  // Variant/Exception/Edge Case scaffolding (all optional, unused by
  // HAPPY_PATH scenarios). One definition, many impacts: a Variant lives
  // once, originates in `feature`/`trigger`, and may affect nodes that
  // belong to several other Features via `affected_nodes`.
  feature?: string;
  applies_to?: string[];
  trigger?: ScenarioTrigger;
  affected_nodes?: string[];
  rules?: string[];
  dependencies?: ScenarioDependencies;
}

export interface ScenarioModel {
  process: {
    id: string;
    version: string;
  };
  scenarios: Scenario[];
}
