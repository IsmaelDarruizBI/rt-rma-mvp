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

/**
 * Business-layer identity: items of these types are references/cache of
 * the business Source of Truth, never new definitions. Keyed by the
 * traceability `type`.
 */
export const BUSINESS_SOURCES: Record<string, { file: string; listKey: string; idPrefix?: string }> = {
  feature: { file: "business/features/repair-management-features-v1.3.yaml", listKey: "features" },
  business_rule: { file: "business/rules/business-rules-v1.3.yaml", listKey: "rules" },
  process_node: { file: "business/processes/repair-management-v1.3.yaml", listKey: "nodes", idPrefix: "PROC-" },
  business_event: { file: "business/processes/repair-management-v1.3.yaml", listKey: "nodes", idPrefix: "EVT-" },
  scenario: { file: "business/scenarios/repair-management-scenarios-v1.3.yaml", listKey: "scenarios" },
};

/** type -> (id -> name) as declared by the Source of Truth. */
export type BusinessCatalog = Record<string, Map<string, string>>;

export type BusinessIssue = {
  kind: "missing" | "name-mismatch";
  id: string;
  type: string;
  file: string;
  traceabilityName?: string;
  businessName?: string;
  expectedSource: string;
};

export type BusinessResult = { checked: number; missing: number; nameMismatches: number; issues: BusinessIssue[] };

export function checkBusinessIdentity(inputs: TraceFileItems[], catalog: BusinessCatalog): BusinessResult {
  const issues: BusinessIssue[] = [];
  let checked = 0;
  for (const { file, items } of inputs) {
    for (const item of items) {
      const type = item.type ?? "";
      const source = BUSINESS_SOURCES[type];
      if (!source) continue;
      checked++;
      const businessName = catalog[type]?.get(item.id);
      if (businessName === undefined) {
        issues.push({ kind: "missing", id: item.id, type, file, expectedSource: source.file });
      } else if (businessName !== item.name) {
        issues.push({
          kind: "name-mismatch",
          id: item.id,
          type,
          file,
          traceabilityName: item.name,
          businessName,
          expectedSource: source.file,
        });
      }
    }
  }
  return {
    checked,
    missing: issues.filter((i) => i.kind === "missing").length,
    nameMismatches: issues.filter((i) => i.kind === "name-mismatch").length,
    issues,
  };
}
