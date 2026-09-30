/**
 * Pure cross-file consistency check for the traceability graphs
 * (traceability/*.yaml). Each file is validated on its own by
 * scripts/validate-traceability.ts; this checks that an item id that
 * appears in more than one file denotes the SAME artifact.
 *
 * A shared id is legitimate (e.g. PROC-REP-212 in two Scenarios). It is a
 * collision when the identity fields differ: `type` and `name` always;
 * `source`, `spec` and `actor` only when both occurrences declare them.
 * Contextual fields (in_scenario, coverage, implemented, note, ...) are
 * deliberately ignored.
 */

export type TraceItem = { id: string; type?: string; name?: string; [key: string]: unknown };
export type TraceFileItems = { file: string; items: TraceItem[] };

export type Collision = {
  id: string;
  occurrences: { file: string; item: TraceItem; differing: string[] }[];
};

export type GlobalResult = {
  files: number;
  uniqueIds: number;
  sharedIds: number;
  collisions: Collision[];
};

const ALWAYS_COMPARED = ["type", "name"] as const;
const COMPARED_IF_BOTH = ["source", "spec", "actor"] as const;

function differs(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) !== JSON.stringify(b);
}

function differingFields(a: TraceItem, b: TraceItem): string[] {
  const out: string[] = ALWAYS_COMPARED.filter((f) => differs(a[f], b[f]));
  for (const f of COMPARED_IF_BOTH) {
    if (a[f] !== undefined && b[f] !== undefined && differs(a[f], b[f])) out.push(f);
  }
  return out;
}

export function checkGlobalConsistency(inputs: TraceFileItems[]): GlobalResult {
  const registry = new Map<string, { file: string; item: TraceItem }[]>();
  for (const { file, items } of inputs) {
    for (const item of items) {
      const list = registry.get(item.id) ?? [];
      list.push({ file, item });
      registry.set(item.id, list);
    }
  }

  const collisions: Collision[] = [];
  let sharedIds = 0;
  for (const [id, occs] of registry) {
    const files = new Set(occs.map((o) => o.file));
    if (files.size < 2) continue;
    sharedIds++;
    const first = occs[0];
    const differing = new Set<string>();
    for (const other of occs.slice(1)) {
      for (const f of differingFields(first.item, other.item)) differing.add(f);
    }
    if (differing.size > 0) {
      collisions.push({
        id,
        occurrences: occs.map((o) => ({ file: o.file, item: o.item, differing: [...differing] })),
      });
    }
  }

  return { files: inputs.length, uniqueIds: registry.size, sharedIds, collisions };
}
