/**
 * Shared types for the Feature Definition YAML model
 * (business/features/*.yaml). Mirrors the shape validated by
 * business/schemas/feature.schema.json.
 *
 * Used by validate-features.ts and validate-references.ts so the shape of
 * a Feature is defined in exactly one place instead of duplicated locally
 * in each script; the viewer will also need these types in a future
 * evolution (Feature <-> Business Process visualization).
 *
 * No business logic here - types only. Loading is done via `loadYaml`
 * from ./process-model, reused rather than duplicated.
 */

export interface FeatureSourceProcess {
  id: string;
  version: string;
}

export interface FeatureScope {
  includes: string[];
  excludes: string[];
}

export type SharedNodeBindingMode = "ALWAYS" | "CONTEXTUAL";

/** Identifies a process edge the same way everywhere in this repo: from + condition + to, never from/to alone. */
export interface SharedNodeBindingEdgeRef {
  from: string;
  to: string;
  condition?: string;
}

export interface SharedNodeBindingWhen {
  // Only incoming_edges exists today; an outgoing_edges sibling could be
  // added later without a shape change (see scenario.schema.json's
  // equivalent step-edge shape for the same from+condition+to identity).
  incoming_edges: SharedNodeBindingEdgeRef[];
}

/**
 * Declares how a Feature participates in a process_node it shares with at
 * least one other Feature (see docs/discovery/README.md, "Feature <->
 * Process Node compartido"): ALWAYS means the Feature's behavior runs
 * every time the node is reached; CONTEXTUAL means it only runs when the
 * node was reached via one of `when.incoming_edges` - other Features
 * sharing the same node may be active via a different edge, or via
 * ALWAYS, without this Feature being involved at all.
 */
export interface SharedNodeBinding {
  node: string;
  mode: SharedNodeBindingMode;
  when?: SharedNodeBindingWhen;
}

export interface FeatureDefinition {
  id: string;
  name: string;
  status: string;
  source_process: FeatureSourceProcess;
  purpose: string;
  inputs: string[];
  outputs: string[];
  /**
   * Optional, PROCESS by default. A TRANSVERSAL Feature (permissions,
   * configuration administration) owns no process node: process_nodes is
   * empty and governed_nodes lists the nodes whose responsibles or
   * configuration it governs. Ownership-based logic (scenario activation,
   * node coverage) never treats governed_nodes as ownership.
   */
  kind?: "PROCESS" | "TRANSVERSAL";
  process_nodes: string[];
  governed_nodes?: string[];
  /** Optional (V1.2 Features predate this field and never declare it). */
  shared_node_bindings?: SharedNodeBinding[];
  business_rules: string[];
  scope: FeatureScope;
  open_questions: string[];
}

export interface FeatureModel {
  process: {
    id: string;
    version: string;
  };
  features: FeatureDefinition[];
}
