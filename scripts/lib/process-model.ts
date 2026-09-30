/**
 * Shared types and Mermaid-rendering helpers for the business process YAML
 * model. Used by both generate-mermaid.ts and generate-process-viewer.ts so
 * the two never diverge on how nodes/edges become Mermaid syntax.
 */
import { readFileSync } from "node:fs";
import { parse } from "yaml";

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

/**
 * Identifies a process edge by from + condition + to, never by from/to alone
 * (several transitions can exist between the same two nodes, and an edge
 * without a condition never matches one that has one). The single
 * definition shared by the validators, the Feature mapping and the
 * scenario-candidate discovery.
 */
export function edgeKey(from: string, condition: string | undefined, to: string): string {
  return `${from}::${condition ?? ""}::${to}`;
}

export function loadYaml<T>(filePath: string): T {
  return parse(readFileSync(filePath, "utf8")) as T;
}

/** Escapes text so it is safe to place inside a quoted Mermaid node label. */
export function escapeLabel(text: string): string {
  return text.replace(/"/g, "'");
}

/** Wraps a node id in the Mermaid shape that corresponds to its process node type. */
export function renderNodeShape(node: ProcessNode): string {
  const label = escapeLabel(node.name);
  switch (node.type) {
    case "start":
      return `${node.id}(["${label}"])`;
    case "end":
      return `${node.id}((("${label}")))`;
    case "decision":
      return `${node.id}{"${label}"}`;
    case "event":
      return `${node.id}{{"${label}"}}`;
    case "activity":
    default:
      return `${node.id}["${label}"]`;
  }
}

export function renderEdgeLine(edge: ProcessEdge): string {
  if (edge.condition) {
    return `${edge.from} -->|${escapeLabel(edge.condition)}| ${edge.to}`;
  }
  return `${edge.from} --> ${edge.to}`;
}

/**
 * Builds the indented "flowchart TD" body (nodes, blank line, edges) shared
 * by every renderer. Callers prepend their own header/comments and the
 * "flowchart TD" line.
 */
export function buildFlowchartBody(model: ProcessModel): string[] {
  const lines: string[] = [];

  for (const node of model.nodes) {
    lines.push(`    ${renderNodeShape(node)}`);
  }

  lines.push("");

  for (const edge of model.edges) {
    lines.push(`    ${renderEdgeLine(edge)}`);
  }

  return lines;
}

/** Mermaid "click" directives binding each node to a JS callback, for interactive viewers. */
export function buildClickDirectives(nodes: ProcessNode[], callbackName: string): string[] {
  return nodes.map((node) => `    click ${node.id} call ${callbackName}("${node.id}")`);
}
