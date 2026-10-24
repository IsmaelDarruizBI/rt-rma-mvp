/**
 * Reproducible, read-only "view by order origin" of a business process.
 *
 * It NEVER edits the Source of Truth: it takes the parsed process model and
 * scenarios and returns a SUBSET of the real nodes/edges (never a new node
 * or edge) that applies to one origin (e.g. CLIENTE_EXTERNO).
 *
 * The filter is semantic, not textual. An edge is removed for the target
 * origin only for one of these explicit reasons (each is reported):
 *
 *  1. EXPLICIT_OTHER_ORIGIN - the edge condition is keyed to the origin
 *     model: it names another origin (RT_INTERNO, RMA_GARANTIA_REPARACION,
 *     RT_GARANTIA_VENTA) or negates the target ("Origen distinto de
 *     CLIENTE_EXTERNO", "..., origen distinto de CLIENTE_EXTERNO").
 *  2. SCENARIO_EVIDENCE - the condition is origin-neutral (e.g. the "No"
 *     branch of PROC-REP-250) but every Scenario that traverses the edge
 *     belongs to another origin, and no Scenario of the target origin (or
 *     generic Scenario) traverses it. A Scenario's origin comes from its
 *     own origin-keyed steps or, when it has none, from the Happy Path it
 *     applies_to. This is the only place where the model does not encode
 *     the origin explicitly on the edge; the report lists those edges so a
 *     reviewer can confirm them.
 *  3. UNREACHABLE - after (1)/(2), the node cannot be reached from any
 *     remaining start event, or the start event has no remaining edge.
 *
 * Topological reachability alone is never used to KEEP an edge as valid for
 * the origin: an edge survives only if its condition is neutral or
 * target-keyed and no scenario evidence excludes it.
 */
import { edgeKey, type FlowchartOptions, type ProcessEdge, type ProcessModel, type ProcessNode } from "./process-model";
import type { Scenario } from "./scenario-model";

export const ORIGINS = ["CLIENTE_EXTERNO", "RT_INTERNO", "RT_GARANTIA_VENTA", "RMA_GARANTIA_REPARACION"] as const;
export type Origin = (typeof ORIGINS)[number];

export type ConditionOrigin = "TARGET" | "OTHER" | "NEUTRAL";

/** Classifies an edge condition with respect to the target origin. */
export function classifyCondition(condition: string | undefined, target: Origin): ConditionOrigin {
  if (!condition) return "NEUTRAL";
  const text = condition;
  // Negation of the target origin: the edge is for every origin EXCEPT the target.
  if (new RegExp(`distinto de\\s+${target}\\b`, "i").test(text)) return "OTHER";
  // Negation of another origin: the edge applies to the target.
  for (const origin of ORIGINS) {
    if (origin !== target && new RegExp(`distinto de\\s+${origin}\\b`, "i").test(text)) return "TARGET";
  }
  const named = ORIGINS.filter((origin) => new RegExp(`\\b${origin}\\b`).test(text));
  if (named.length === 0) return "NEUTRAL";
  return named.includes(target) ? "TARGET" : "OTHER";
}

/** Origins named POSITIVELY (not negated) by a condition. */
function positiveOrigins(condition: string | undefined): Origin[] {
  if (!condition) return [];
  return ORIGINS.filter((origin) => new RegExp(`\\b${origin}\\b`).test(condition) && !new RegExp(`distinto de\\s+${origin}\\b`, "i").test(condition));
}

export type ScenarioOrigins = Origin[] | "ALL";

/**
 * Origin(s) a Scenario belongs to. Own origin-keyed steps win; otherwise the
 * Happy Paths it applies_to (recursively); a Scenario that applies to every
 * Happy Path of the model (or to none) is generic ("ALL").
 */
export function scenarioOrigins(scenarios: Scenario[]): Map<string, ScenarioOrigins> {
  const byId = new Map(scenarios.map((s) => [s.id, s]));
  const memo = new Map<string, ScenarioOrigins>();
  const happyPaths = scenarios.filter((s) => s.type === "HAPPY_PATH");

  const own = (s: Scenario): Origin[] => {
    const found = new Set<Origin>();
    for (const step of s.steps ?? []) {
      if (step.kind === "PROCESS_EDGE") for (const o of positiveOrigins(step.condition)) found.add(o);
    }
    return [...found];
  };

  const resolve = (id: string, trail: string[]): ScenarioOrigins => {
    const cached = memo.get(id);
    if (cached) return cached;
    const s = byId.get(id);
    if (!s || trail.includes(id)) return "ALL";
    let result: ScenarioOrigins;
    const mine = own(s);
    if (mine.length > 0) {
      result = mine;
    } else {
      const applies = (s.applies_to ?? []).filter((x) => byId.has(x));
      if (applies.length === 0 || applies.length >= happyPaths.length) {
        result = "ALL";
      } else {
        const union = new Set<Origin>();
        let all = false;
        for (const a of applies) {
          const o = resolve(a, [...trail, id]);
          if (o === "ALL") all = true;
          else o.forEach((x) => union.add(x));
        }
        result = all ? "ALL" : [...union];
      }
    }
    memo.set(id, result);
    return result;
  };

  for (const s of scenarios) resolve(s.id, []);
  return memo;
}

export type ExclusionReason = "EXPLICIT_OTHER_ORIGIN" | "SCENARIO_EVIDENCE" | "UNREACHABLE";

export interface OriginViewReport {
  origin: Origin;
  primaryStart: string;
  startEvents: string[];
  excludedEdges: { edge: ProcessEdge; reason: ExclusionReason; detail: string }[];
  excludedNodes: { id: string; name: string; reason: string }[];
  keptScenarios: string[];
  excludedScenarios: { id: string; reason: string }[];
  /** Edges that leave a secondary start event (independent lane, e.g. EVT-REP-003 -> PROC-REP-046). */
  laneEdgeKeys: string[];
}

export interface OriginView {
  model: ProcessModel;
  scenarios: Scenario[];
  report: OriginViewReport;
}

function reachableFrom(starts: string[], edges: ProcessEdge[]): Set<string> {
  const out = new Map<string, string[]>();
  for (const e of edges) {
    if (!out.has(e.from)) out.set(e.from, []);
    out.get(e.from)?.push(e.to);
  }
  const seen = new Set<string>(starts);
  const queue = [...starts];
  while (queue.length) {
    const cur = queue.shift() as string;
    for (const next of out.get(cur) ?? []) {
      if (!seen.has(next)) {
        seen.add(next);
        queue.push(next);
      }
    }
  }
  return seen;
}

export function buildOriginView(model: ProcessModel, scenarios: Scenario[], target: Origin): OriginView {
  const origins = scenarioOrigins(scenarios);
  const excludedEdges: OriginViewReport["excludedEdges"] = [];

  // Which scenarios traverse each edge, and are those scenarios of the target origin?
  const usedBy = new Map<string, string[]>();
  for (const s of scenarios) {
    for (const step of s.steps ?? []) {
      if (step.kind !== "PROCESS_EDGE") continue;
      const key = edgeKey(step.from, step.condition, step.to);
      if (!usedBy.has(key)) usedBy.set(key, []);
      usedBy.get(key)?.push(s.id);
    }
  }
  const appliesToTarget = (id: string): boolean => {
    const o = origins.get(id) ?? "ALL";
    return o === "ALL" || o.includes(target);
  };

  const kept: ProcessEdge[] = [];
  for (const edge of model.edges) {
    const cls = classifyCondition(edge.condition, target);
    if (cls === "OTHER") {
      excludedEdges.push({ edge, reason: "EXPLICIT_OTHER_ORIGIN", detail: `condicion "${edge.condition}"` });
      continue;
    }
    if (cls === "NEUTRAL") {
      const users = usedBy.get(edgeKey(edge.from, edge.condition, edge.to)) ?? [];
      if (users.length > 0 && !users.some(appliesToTarget)) {
        excludedEdges.push({ edge, reason: "SCENARIO_EVIDENCE", detail: `solo la recorren ${users.join(", ")} (otro origen)` });
        continue;
      }
    }
    kept.push(edge);
  }

  // Start events: event nodes with no incoming edge in the full model.
  const hasIncoming = new Set(model.edges.map((e) => e.to));
  const allStarts = model.nodes.filter((n) => n.type === "event" && !hasIncoming.has(n.id)).map((n) => n.id);
  const hpOfTarget = scenarios.find((s) => s.type === "HAPPY_PATH" && (origins.get(s.id) ?? []) !== "ALL" && (origins.get(s.id) as Origin[]).includes(target));
  const firstStep = hpOfTarget?.steps?.find((st) => st.kind === "PROCESS_EDGE");
  const primaryStart = firstStep && firstStep.kind === "PROCESS_EDGE" ? firstStep.from : allStarts[0];

  const keptFrom = new Set(kept.map((e) => e.from));
  const startEvents = allStarts.filter((id) => keptFrom.has(id));
  const reachable = reachableFrom(startEvents, kept);

  const finalEdges = kept.filter((e) => reachable.has(e.from) && reachable.has(e.to));
  for (const edge of kept) {
    if (!finalEdges.includes(edge)) excludedEdges.push({ edge, reason: "UNREACHABLE", detail: "queda inalcanzable tras filtrar" });
  }
  const finalNodes: ProcessNode[] = model.nodes.filter((n) => reachable.has(n.id));
  const excludedNodes = model.nodes
    .filter((n) => !reachable.has(n.id))
    .map((n) => ({ id: n.id, name: n.name, reason: allStarts.includes(n.id) ? "evento de inicio de otro origen" : "solo alcanzable por aristas de otro origen" }));

  // Scenarios: keep those of the target origin (or generic) whose every process edge survives.
  const finalKeys = new Set(finalEdges.map((e) => edgeKey(e.from, e.condition, e.to)));
  const keptScenarios: Scenario[] = [];
  const excludedScenarios: OriginViewReport["excludedScenarios"] = [];
  for (const s of scenarios) {
    if (!appliesToTarget(s.id)) {
      excludedScenarios.push({ id: s.id, reason: `pertenece a otro origen (${(origins.get(s.id) as Origin[]).join(", ")})` });
      continue;
    }
    const missing = (s.steps ?? []).filter((st) => st.kind === "PROCESS_EDGE" && !finalKeys.has(edgeKey(st.from, st.condition, st.to)));
    if (missing.length > 0) {
      excludedScenarios.push({ id: s.id, reason: `recorre aristas fuera de la vista (${missing.length})` });
      continue;
    }
    keptScenarios.push(s);
  }

  const secondaryStarts = startEvents.filter((id) => id !== primaryStart);
  const laneEdgeKeys = finalEdges.filter((e) => secondaryStarts.includes(e.from)).map((e) => edgeKey(e.from, e.condition, e.to));

  return {
    model: { ...model, nodes: finalNodes, edges: finalEdges },
    scenarios: keptScenarios,
    report: {
      origin: target,
      primaryStart,
      startEvents,
      excludedEdges,
      excludedNodes,
      keptScenarios: keptScenarios.map((s) => s.id),
      excludedScenarios,
      laneEdgeKeys,
    },
  };
}

export function isOrigin(value: string): value is Origin {
  return (ORIGINS as readonly string[]).includes(value);
}

/** Slug used in generated file names, e.g. CLIENTE_EXTERNO -> cliente-externo. */
export function originSlug(origin: Origin): string {
  return origin.toLowerCase().replace(/_/g, "-");
}

/** Inserts the origin slug before the version suffix: repair-management-v1.4 -> repair-management-cliente-externo-v1.4. */
export function originStem(stem: string, origin: Origin): string {
  return stem.replace(/^(.*?)(-v\d.*)?$/, (_m, base: string, version: string | undefined) => `${base}-${originSlug(origin)}${version ?? ""}`);
}

/**
 * Presentation hooks for the per-origin diagram: the actor is printed in each
 * node label and the edges of the independent lane (leaving a secondary start
 * event, e.g. EVT-REP-003 -> PROC-REP-046) are drawn dotted so they are not
 * read as a mandatory step of the technical thread.
 */
export function originFlowchartOptions(view: OriginView, actorNames: Map<string, string>): FlowchartOptions {
  const lane = new Set(view.report.laneEdgeKeys);
  return {
    nodeLabel: (node) => (node.actor ? `${node.name}<br/>[${actorNames.get(node.actor) ?? node.actor}]` : node.name),
    edgeArrow: (edge) => (lane.has(edgeKey(edge.from, edge.condition, edge.to)) ? "-.->" : "-->"),
  };
}

/** Human label of an origin, used in titles. */
export function originLabel(origin: Origin): string {
  switch (origin) {
    case "CLIENTE_EXTERNO":
      return "Cliente Externo";
    case "RT_INTERNO":
      return "Equipo Interno RT";
    case "RMA_GARANTIA_REPARACION":
      return "Garantia RMA";
    case "RT_GARANTIA_VENTA":
      return "Garantia de Venta RT";
  }
}
