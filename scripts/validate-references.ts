/**
 * Validates referential integrity across the business YAML files:
 * repair-management.yaml, repair-management-features.yaml,
 * business-rules.yaml and actors.yaml.
 *
 * This is a different concern from validate-process.ts / validate-features.ts:
 * those check the SHAPE of a single YAML file in isolation (JSON Schema).
 * This script checks that IDs referenced in one file actually exist in
 * another (edges -> nodes, nodes -> actors/rules, Features -> process
 * nodes/rules, etc.) and reports Feature coverage. It runs after both
 * structural validators, never replaces them, and never edits the source
 * YAML to "fix" what it finds: inconsistencies are reported, not corrected.
 *
 * The validation functions below take already-loaded data (not file paths)
 * so they can also be exercised directly - e.g. against deliberately
 * corrupted in-memory copies - without touching any file on disk.
 *
 * All four source files are parameterizable via optional positional CLI
 * args (`tsx scripts/validate-references.ts [processFile] [rulesFile]
 * [actorsFile] [featuresFile]`), so this one script also cross-validates
 * a draft revision (e.g. PROC-REP V1.3, which has its own process +
 * rules files and, deliberately, no Features yet) without duplicating
 * this logic per version. Invoked with zero args (the existing `npm run
 * validate:references`), behavior is unchanged: validates V1.2 with its
 * approved Features. Invoked with explicit args and no 4th (features)
 * arg, the Features-vs-process checks and coverage reports are skipped
 * entirely rather than silently falling back to V1.2's Features file.
 */
import { pathToFileURL } from "node:url";
import {
  loadYaml,
  type Actor,
  type BusinessRule,
  type NodeType,
  type ProcessModel,
  type ProcessNode,
} from "./lib/process-model";
import type { FeatureModel } from "./lib/feature-model";
import { validateSharedNodeBindings } from "./lib/feature-scenario-mapping";

const DEFAULT_PROCESS_FILE = "business/processes/repair-management.yaml";
const DEFAULT_FEATURES_FILE = "business/features/repair-management-features.yaml";
const DEFAULT_RULES_FILE = "business/rules/business-rules.yaml";
const DEFAULT_ACTORS_FILE = "business/actors/actors.yaml";

const cliArgs = process.argv.slice(2);
const isDefaultRun = cliArgs.length === 0;

const PROCESS_FILE = cliArgs[0] ?? DEFAULT_PROCESS_FILE;
const RULES_FILE = cliArgs[1] ?? DEFAULT_RULES_FILE;
const ACTORS_FILE = cliArgs[2] ?? DEFAULT_ACTORS_FILE;
// Zero-arg invocation: default to V1.2's Features (unchanged behavior).
// Any explicit invocation: Features are validated only if a 4th arg was
// actually given - an omitted 4th arg means "this revision has no
// Features file yet" (e.g. V1.3 during this iteration), not "use V1.2's".
const FEATURES_FILE: string | null = isDefaultRun ? DEFAULT_FEATURES_FILE : cliArgs[3] || null;

// Node types excluded from "functional" coverage accounting (events and
// start/end markers aren't operational work a Feature performs).
const NON_FUNCTIONAL_NODE_TYPES: ReadonlySet<NodeType> = new Set(["event", "start", "end"]);

export interface Report {
  errors: string[];
  warnings: string[];
}

export function findDuplicates(ids: string[]): string[] {
  const seen = new Set<string>();
  const duplicates = new Set<string>();
  for (const id of ids) {
    if (seen.has(id)) duplicates.add(id);
    seen.add(id);
  }
  return [...duplicates];
}

/**
 * Adds `ownerId` to the set of owners stored at `key`, creating the set if
 * needed. Every reverse index in this file is built this way
 * (Map<string, Set<string>>), never as Map<string, string>: a node or a
 * rule can legitimately belong to more than one Feature (N:M), and a plain
 * 1:1 map would silently drop that.
 */
function addToIndex(index: Map<string, Set<string>>, key: string, ownerId: string): void {
  const owners = index.get(key) ?? new Set<string>();
  owners.add(ownerId);
  index.set(key, owners);
}

// --- 3. Business Process internal integrity -------------------------------

export function validateCatalogIntegrity(rules: BusinessRule[], actors: Actor[], report: Report): void {
  for (const id of findDuplicates(rules.map((rule) => rule.id))) {
    report.errors.push(`[business-rules] id de Business Rule duplicado: ${id}`);
  }
  for (const id of findDuplicates(actors.map((actor) => actor.id))) {
    report.errors.push(`[actors] id de Actor duplicado: ${id}`);
  }
}

export function validateProcessIntegrity(
  processModel: ProcessModel,
  actorsById: Map<string, Actor>,
  rulesById: Map<string, BusinessRule>,
  report: Report
): void {
  for (const id of findDuplicates(processModel.nodes.map((node) => node.id))) {
    report.errors.push(`[process] id de node duplicado: ${id}`);
  }

  const nodeIds = new Set(processModel.nodes.map((node) => node.id));
  for (const edge of processModel.edges) {
    if (!nodeIds.has(edge.from)) {
      report.errors.push(`[process] edge.from inexistente: "${edge.from}" (-> ${edge.to})`);
    }
    if (!nodeIds.has(edge.to)) {
      report.errors.push(`[process] edge.to inexistente: "${edge.to}" (${edge.from} ->)`);
    }
  }

  for (const node of processModel.nodes) {
    if (node.actor && !actorsById.has(node.actor)) {
      report.errors.push(`[process] ${node.id}: actor inexistente "${node.actor}"`);
    }
    for (const actorId of node.actores_alternativos ?? []) {
      if (!actorsById.has(actorId)) {
        report.errors.push(`[process] ${node.id}: actor alternativo inexistente "${actorId}"`);
      }
      if (actorId === node.actor) {
        report.errors.push(
          `[process] ${node.id}: "${actorId}" ya es el actor principal, no corresponde repetirlo como alternativo`
        );
      }
    }
    for (const ruleId of node.rules ?? []) {
      if (!rulesById.has(ruleId)) {
        report.errors.push(`[process] ${node.id}: business rule inexistente "${ruleId}"`);
      }
    }
  }
}

// --- 4. Features vs. Business Process --------------------------------------

export function validateFeaturesAgainstProcess(
  featuresModel: FeatureModel,
  processModel: ProcessModel,
  nodeIds: Set<string>,
  rulesById: Map<string, BusinessRule>,
  report: Report
): void {
  if (featuresModel.process.id !== processModel.process.id) {
    report.errors.push(
      `[features] process.id "${featuresModel.process.id}" no coincide con el Business Process ` +
        `"${processModel.process.id}"`
    );
  }
  if (featuresModel.process.version !== processModel.process.version) {
    report.errors.push(
      `[features] process.version "${featuresModel.process.version}" no coincide con la version ` +
        `del Business Process "${processModel.process.version}"`
    );
  }

  for (const feature of featuresModel.features) {
    if (feature.source_process.id !== processModel.process.id) {
      report.errors.push(
        `[features] ${feature.id}: source_process.id "${feature.source_process.id}" no coincide ` +
          `con "${processModel.process.id}"`
      );
    }
    if (feature.source_process.version !== processModel.process.version) {
      report.errors.push(
        `[features] ${feature.id}: source_process.version "${feature.source_process.version}" no ` +
          `coincide con la version aprobada "${processModel.process.version}"`
      );
    }
    for (const nodeId of feature.process_nodes) {
      if (!nodeIds.has(nodeId)) {
        report.errors.push(`[features] ${feature.id}: process_node inexistente "${nodeId}"`);
      }
    }
    for (const nodeId of feature.governed_nodes ?? []) {
      if (!nodeIds.has(nodeId)) {
        report.errors.push(`[features] ${feature.id}: governed_node inexistente "${nodeId}"`);
      }
    }
    for (const ruleId of feature.business_rules) {
      if (!rulesById.has(ruleId)) {
        report.errors.push(`[features] ${feature.id}: business rule inexistente "${ruleId}"`);
      }
    }
  }
}

// --- 5. Feature <-> Node <-> Business Rule consistency (warning only) -----

/**
 * A Feature's business_rules[] should ideally be backed by at least one of
 * its own process_nodes also declaring that same rule in its rules[]: that
 * shows the Feature -> Business Rule relationship is grounded in the
 * approved Business Process, not just asserted at the Feature level. This
 * is intentionally a warning, not an error: future transversal Features
 * may legitimately reference a rule without owning the node that carries
 * it, and this stage shouldn't impose a semantic rule that rigid yet.
 */
export function validateFeatureRuleNodeConsistency(
  featuresModel: FeatureModel,
  nodesById: Map<string, ProcessNode>,
  report: Report
): void {
  for (const feature of featuresModel.features) {
    // A TRANSVERSAL Feature owns no node: its rules are backed by the nodes it governs.
    const backingNodes = feature.kind === "TRANSVERSAL" ? feature.governed_nodes ?? [] : feature.process_nodes;
    for (const ruleId of feature.business_rules) {
      const backedByNode = backingNodes.some((nodeId) =>
        (nodesById.get(nodeId)?.rules ?? []).includes(ruleId)
      );
      if (!backedByNode) {
        report.warnings.push(
          `[feature<->node<->rule] ${feature.id}: declara "${ruleId}" en business_rules, pero ` +
            `ningun process_node de la Feature la referencia en su propio rules[]`
        );
      }
    }
  }
}

// --- 6/7. Coverage (informational only, never an error) --------------------

export interface CoverageResult {
  total: number;
  covered: number;
  uncoveredIds: string[];
  sharedIds: string[];
}

/**
 * Builds a reverse index (item id -> set of owning Feature ids) from
 * feature.<field>[], restricted to ids present in `universe`, then derives
 * coverage/uncovered/shared from it. Shared by design with node and rule
 * coverage so both follow the exact same N:M-safe logic.
 */
function computeCoverage(
  universe: ReadonlySet<string>,
  featuresModel: FeatureModel,
  featureField: "process_nodes" | "business_rules"
): CoverageResult {
  const index = new Map<string, Set<string>>();
  for (const feature of featuresModel.features) {
    for (const itemId of feature[featureField]) {
      if (universe.has(itemId)) {
        addToIndex(index, itemId, feature.id);
      }
    }
  }

  const uncoveredIds = [...universe].filter((id) => !index.has(id));
  const sharedIds = [...index.entries()]
    .filter(([, owners]) => owners.size > 1)
    .map(([id]) => id);

  return {
    total: universe.size,
    covered: universe.size - uncoveredIds.length,
    uncoveredIds,
    sharedIds,
  };
}

export function computeNodeCoverage(processModel: ProcessModel, featuresModel: FeatureModel): CoverageResult {
  const functionalIds = new Set(
    processModel.nodes.filter((node) => !NON_FUNCTIONAL_NODE_TYPES.has(node.type)).map((node) => node.id)
  );
  return computeCoverage(functionalIds, featuresModel, "process_nodes");
}

export function computeRuleCoverage(rules: BusinessRule[], featuresModel: FeatureModel): CoverageResult {
  const ruleIds = new Set(rules.map((rule) => rule.id));
  return computeCoverage(ruleIds, featuresModel, "business_rules");
}

// --- reporting --------------------------------------------------------------

function printCoverage(title: string, coverage: CoverageResult): void {
  console.log(title);
  console.log(`  Total: ${coverage.total}`);
  console.log(`  Covered by Features: ${coverage.covered}`);
  console.log(`  Uncovered: ${coverage.uncoveredIds.length}`);
  if (coverage.uncoveredIds.length > 0) {
    console.log(`    ${coverage.uncoveredIds.join(", ")}`);
  }
  console.log(`  Shared by multiple Features: ${coverage.sharedIds.length}`);
  if (coverage.sharedIds.length > 0) {
    console.log(`    ${coverage.sharedIds.join(", ")}`);
  }
  console.log("");
}

export function main(): void {
  const processModel = loadYaml<ProcessModel>(PROCESS_FILE);
  const featuresModel = FEATURES_FILE ? loadYaml<FeatureModel>(FEATURES_FILE) : null;
  const rules = loadYaml<{ rules: BusinessRule[] }>(RULES_FILE).rules;
  const actors = loadYaml<{ actors: Actor[] }>(ACTORS_FILE).actors;

  const actorsById = new Map(actors.map((actor) => [actor.id, actor]));
  const rulesById = new Map(rules.map((rule) => [rule.id, rule]));
  const nodesById = new Map(processModel.nodes.map((node) => [node.id, node]));

  const report: Report = { errors: [], warnings: [] };

  validateCatalogIntegrity(rules, actors, report);
  validateProcessIntegrity(processModel, actorsById, rulesById, report);

  console.log("=== Validacion de integridad referencial ===\n");

  if (featuresModel) {
    validateFeaturesAgainstProcess(featuresModel, processModel, new Set(nodesById.keys()), rulesById, report);
    validateFeatureRuleNodeConsistency(featuresModel, nodesById, report);
    // Safe for a Features file with zero shared nodes (e.g. V1.2 today):
    // the completeness check inside never fires, so this never forces V1.2
    // to adopt shared_node_bindings. See feature-scenario-mapping.ts.
    for (const error of validateSharedNodeBindings(processModel, featuresModel)) {
      report.errors.push(error);
    }
  } else {
    console.log(
      "Features: omitido (no se proporciono archivo de Features para esta revision del proceso).\n"
    );
  }

  if (report.errors.length > 0) {
    console.error("ERRORES:");
    for (const error of report.errors) console.error(`  - ${error}`);
    console.error("");
  }

  if (report.warnings.length > 0) {
    console.warn("WARNINGS:");
    for (const warning of report.warnings) console.warn(`  - ${warning}`);
    console.warn("");
  }

  if (featuresModel) {
    printCoverage("Coverage - process nodes funcionales (excluye event/start/end):", computeNodeCoverage(processModel, featuresModel));
    printCoverage("Coverage - Business Rules:", computeRuleCoverage(rules, featuresModel));
  }

  if (report.errors.length > 0) {
    console.error(`FAILED: ${report.errors.length} error(es) de integridad referencial.`);
    process.exit(1);
  }

  const validated = [PROCESS_FILE, RULES_FILE, ACTORS_FILE, featuresModel ? FEATURES_FILE : null]
    .filter(Boolean)
    .join(", ");
  console.log(`OK: referencias entre ${validated} son validas.`);
}

// Only run when this file is executed directly (`tsx scripts/validate-references.ts`),
// not when its functions are imported elsewhere (e.g. a test harness exercising
// the validators against in-memory data without touching any YAML file).
if (import.meta.url === pathToFileURL(process.argv[1] ?? "").href) {
  main();
}
