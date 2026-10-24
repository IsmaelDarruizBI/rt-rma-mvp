/**
 * Shared types and Mermaid-rendering helpers for the business process YAML
 * model. Used by both generate-mermaid.ts and generate-process-viewer.ts so
 * the two never diverge on how nodes/edges become Mermaid syntax.
 */
import { readFileSync } from "node:fs";
import { parse } from "yaml";
import { edgeKey, escapeLabel, renderEdgeLine, renderNodeShape } from "./process-core";

export type NodeType = "start" | "end" | "activity" | "decision" | "event";

export interface ProcessNode {
  id: string;
  type: NodeType;
  name: string;
  description?: string;
  actor?: string;
  /**
   * Otros actores igualmente autorizados a ejecutar el nodo, ademas de
   * `actor`. Opcional y retrocompatible: un nodo sin este campo admite
   * unicamente su `actor`. No hay jerarquia entre ellos.
   */
  actores_alternativos?: string[];
  inputs?: string[];
  outputs?: string[];
  rules?: string[];
  systems?: string[];
}

export interface ProcessEdge {
  from: string;
  to: string;
  condition?: string;
}

export interface ProcessModel {
  process: { id: string; name: string; version: string; status?: string };
  nodes: ProcessNode[];
  edges: ProcessEdge[];
}

export interface Actor {
  id: string;
  name: string;
}

export interface BusinessRule {
  id: string;
  name: string;
  description?: string;
  status?: string;
}

// edgeKey, escapeLabel, renderNodeShape and renderEdgeLine are pure (browser-safe) and live in
// process-core.ts, shared with the interactive explorer; they are re-exported here unchanged.
export { edgeKey, escapeLabel, renderEdgeLine, renderNodeShape };

export function loadYaml<T>(filePath: string): T {
  return parse(readFileSync(filePath, "utf8")) as T;
}

/**
 * Optional presentation hooks for filtered/derived views (e.g. the
 * per-origin viewer). Defaults reproduce the general diagram exactly.
 */
export interface FlowchartOptions {
  /** Replaces the text of a node label (default: node.name). */
  nodeLabel?: (node: ProcessNode) => string;
  /** Arrow used to draw an edge (default "-->"; "-.->" draws it dotted). */
  edgeArrow?: (edge: ProcessEdge) => "-->" | "-.->";
}

/**
 * Builds the indented "flowchart TD" body (nodes, blank line, edges) shared
 * by every renderer. Callers prepend their own header/comments and the
 * "flowchart TD" line.
 */
export function buildFlowchartBody(model: ProcessModel, options: FlowchartOptions = {}): string[] {
  const lines: string[] = [];

  for (const node of model.nodes) {
    lines.push(`    ${renderNodeShape(node, options.nodeLabel ? options.nodeLabel(node) : node.name)}`);
  }

  lines.push("");

  for (const edge of model.edges) {
    lines.push(`    ${renderEdgeLine(edge, options.edgeArrow ? options.edgeArrow(edge) : "-->")}`);
  }

  return lines;
}

/** Mermaid "click" directives binding each node to a JS callback, for interactive viewers. */
export function buildClickDirectives(nodes: ProcessNode[], callbackName: string): string[] {
  return nodes.map((node) => `    click ${node.id} call ${callbackName}("${node.id}")`);
}
