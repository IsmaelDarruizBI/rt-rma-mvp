/**
 * Generates a Mermaid flowchart from a business process YAML file.
 *
 * YAML is the single source of truth. This script is a one-way
 * transformation: YAML -> Mermaid. Mermaid is never edited by hand
 * and never read back into the process model.
 *
 * The source file is parameterizable via an optional CLI arg
 * (`tsx scripts/generate-mermaid.ts [sourceFile]`), so the same script
 * generates the diagram for any process revision. The output filename is
 * derived from the source filename's stem, so the default (no arg, V1.2,
 * `repair-management.yaml`) keeps producing exactly
 * `generated/mermaid/repair-management.mmd` as before, while an explicit
 * source like `repair-management-v1.3.yaml` produces a sibling
 * `repair-management-v1.3.mmd` without colliding with V1.2's output.
 *
 * Optional per-origin view (read-only subset of the same model, see
 * scripts/lib/origin-filter.ts):
 *
 *   tsx scripts/generate-mermaid.ts <sourceFile> --origin=CLIENTE_EXTERNO \
 *       --scenarios=<scenariosFile> [--actors=<actorsFile>]
 *
 * writes `generated/mermaid/<stem with the origin slug before the version>.mmd`
 * (e.g. repair-management-cliente-externo-v1.4.mmd). Without --origin the
 * output is byte-identical to previous releases.
 */
import { writeFileSync, mkdirSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { buildFlowchartBody, loadYaml, type Actor, type FlowchartOptions, type ProcessModel } from "./lib/process-model";
import { buildOriginView, isOrigin, originFlowchartOptions, originStem, type Origin, type OriginView } from "./lib/origin-filter";
import type { ScenarioModel } from "./lib/scenario-model";

const DEFAULT_SOURCE_FILE = join("business", "processes", "repair-management.yaml");
const DEFAULT_ACTORS_FILE = join("business", "actors", "actors.yaml");

const rawArgs = process.argv.slice(2);
const flags = new Map<string, string>(
  rawArgs
    .filter((arg) => arg.startsWith("--"))
    .map((arg): [string, string] => {
      const [key, ...value] = arg.slice(2).split("=");
      return [key, value.join("=")];
    })
);
const positionalArgs = rawArgs.filter((arg) => !arg.startsWith("--"));

const SOURCE_FILE = positionalArgs[0] ?? DEFAULT_SOURCE_FILE;
const ORIGIN_FLAG = flags.get("origin");
if (ORIGIN_FLAG !== undefined && !isOrigin(ORIGIN_FLAG)) {
  console.error(`Origen invalido: ${ORIGIN_FLAG}`);
  process.exit(1);
}
const ORIGIN = ORIGIN_FLAG as Origin | undefined;
const SCENARIOS_FILE = flags.get("scenarios");
const ACTORS_FILE = flags.get("actors") ?? DEFAULT_ACTORS_FILE;
const STEM = basename(SOURCE_FILE, ".yaml");
const OUTPUT_FILE = join("generated", "mermaid", `${ORIGIN ? originStem(STEM, ORIGIN) : STEM}.mmd`);

function generateMermaid(model: ProcessModel, view?: OriginView, options?: FlowchartOptions): string {
  const lines: string[] = [];
  lines.push("%% AUTO-GENERATED FILE.");
  lines.push("%% DO NOT EDIT MANUALLY.");
  lines.push(`%% SOURCE: ${SOURCE_FILE.replace(/\\/g, "/")}`);
  if (view) {
    lines.push(`%% VIEW: origen ${view.report.origin} (subconjunto de nodos y aristas reales; ver scripts/lib/origin-filter.ts)`);
    lines.push(`%% Nodos: ${view.model.nodes.length} | Aristas: ${view.model.edges.length} | Aristas punteadas: carril independiente de Recepcion (EVT secundarios)`);
  }
  lines.push("");
  lines.push("flowchart TD");
  lines.push(...buildFlowchartBody(model, options));

  return lines.join("\n") + "\n";
}

function main(): void {
  const model = loadYaml<ProcessModel>(SOURCE_FILE);

  let mermaid: string;
  if (ORIGIN) {
    if (!SCENARIOS_FILE) {
      console.error("--origin requiere --scenarios=<archivo de Scenarios> (se usa como evidencia de origen).");
      process.exit(1);
    }
    const scenarios = loadYaml<ScenarioModel>(SCENARIOS_FILE).scenarios;
    const actors = loadYaml<{ actors: Actor[] }>(ACTORS_FILE).actors;
    const view = buildOriginView(model, scenarios, ORIGIN);
    mermaid = generateMermaid(view.model, view, originFlowchartOptions(view, new Map(actors.map((a) => [a.id, a.name]))));
  } else {
    mermaid = generateMermaid(model);
  }

  mkdirSync(dirname(OUTPUT_FILE), { recursive: true });
  writeFileSync(OUTPUT_FILE, mermaid, "utf8");

  console.log(`Mermaid diagram generated: ${OUTPUT_FILE}`);
}

main();
