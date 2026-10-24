/**
 * Pure helpers shared by the Node generators AND the browser-side interactive
 * explorer. They have no runtime imports (only erased type imports), so the
 * same source can be transpiled into the self-contained HTML viewer without
 * duplicating logic.
 *
 * process-model.ts re-exports everything here: existing imports keep working
 * and the output of every existing generator is unchanged.
 */
import type { ProcessEdge, ProcessNode } from "./process-model";

/**
 * Identifies a process edge by from + condition + to, never by from/to alone
 * (several transitions can exist between the same two nodes, and an edge
 * without a condition never matches one that has one). The single
 * definition shared by the validators, the Feature mapping, the
 * scenario-candidate discovery and the interactive explorer.
 */
export function edgeKey(from: string, condition: string | undefined, to: string): string {
  return `${from}::${condition ?? ""}::${to}`;
}

/** Escapes text so it is safe to place inside a quoted Mermaid node label. */
export function escapeLabel(text: string): string {
  return text.replace(/"/g, "'");
}

/** Wraps a node id in the Mermaid shape that corresponds to its process node type. */
export function renderNodeShape(node: ProcessNode, labelText: string = node.name): string {
  const label = escapeLabel(labelText);
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

export function renderEdgeLine(edge: ProcessEdge, arrow: "-->" | "-.->" = "-->"): string {
  if (edge.condition) {
    return `${edge.from} ${arrow}|${escapeLabel(edge.condition)}| ${edge.to}`;
  }
  return `${edge.from} ${arrow} ${edge.to}`;
}
